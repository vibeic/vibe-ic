#!/usr/bin/env python3
"""A declared artefact appears under its final name only once it is complete.

vibe-ic#1082. Adopted from OpenROAD-flow-scripts (`flow/scripts/flow.sh:9`),
which buys the invariant with one line:

    trap 'mv "$LOG_DIR/$1.tmp.log" "$LOG_DIR/$1.log"' EXIT

WHAT THE INVARIANT IS
=====================
The final filename existing IMPLIES the write ran to completion. Structurally,
not by convention — there is no window in which the final name refers to a
half-written artefact, because the final name is created by a rename of an
already-complete file.

WHY THIS REPO NEEDS IT
======================
`Path.write_text` — the idiom essentially every writer here uses — opens the
destination, TRUNCATES it, and writes. A process that dies between the truncate
and the last byte leaves a short file under the final name, and nothing
downstream can tell it apart from a complete one.

The consumer that inherits the lie is `required_outputs`. MEASURED at
`4b22e36ea`, its presence predicate is `flow_compliance_check`
`_resolves_to_real_artefact`, whose own docstring states the rule:

    Non-symlinks are returned True UNCONDITIONALLY and deliberately

That is the correct rule for the question it was written to answer (a dangling
symlink is not a produced artefact). It means the predicate says nothing
whatever about completeness: a 0-byte file, a JSON truncated mid-object, and a
finished report are the same answer. So under this defect a `required_outputs`
PASS asserts that a directory entry exists — which is almost nothing — and the
step is credited with having produced its declared output.

This is the empty-tree shape at the artefact level: the file exists, so the
check proceeds, and it proceeds over nothing.

WHAT THIS CHANGES, AND WHAT IT DELIBERATELY DOES NOT
====================================================
It changes WHEN a filename appears. It does not change what any check MEANS.
`required_outputs` still asks exactly what it asked before; the difference is
that the artefact it finds is now necessarily complete, so the question it was
always asking finally has the answer it was always assumed to have.

THE HONEST LIMIT OF "NOTHING EXISTS UNDER THE FINAL NAME"
=========================================================
True for the first write of an artefact, which is the case #1082 is about, and
the case the two-arm control exercises.

On a RE-run over an artefact that already exists, `os.replace` leaves the
PREVIOUS complete artefact in place when the new write dies. That is the
strongest guarantee an atomic rename can give and it is the right one: the
final name always refers to SOME complete artefact, never to a partial one.
It is not a staleness guarantee, and this module does not claim to be one —
staleness is a different defect with its own checks in this tree, and
conflating them here would be this module asserting something it cannot see.

WHY A TEMP SIBLING AND NOT A TEMP DIRECTORY
===========================================
`os.replace` is atomic only WITHIN a filesystem. A temp file in `/tmp` and a
destination under the project can be on different mounts, where `os.replace`
falls back to a copy and reintroduces exactly the partial-file window this
module exists to close. The temp is therefore always created in the
DESTINATION'S OWN DIRECTORY, so the rename cannot cross a mount.

The temp name carries the pid so two processes writing the same artefact
concurrently cannot truncate each other's temp file. They still race for the
final name, and the winner is whichever renames last — atomically, so a reader
sees one complete artefact or the other, never a mixture.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Union

__all__ = [
    "TMP_SUFFIX",
    "temp_name_for",
    "writing",
    "write_text",
    "write_bytes",
    "write_json",
    "is_temp_artefact",
]

#: Marker that makes a partial artefact RECOGNISABLE rather than merely
#: invisible. A leftover from a killed process is named `<final>.tmp.<pid>` and
#: a human or a sweeper can tell at a glance what it is and which process owned
#: it — the alternative, an opaque `tmpXXXXXX`, is litter nobody can attribute.
TMP_SUFFIX = ".tmp"


def temp_name_for(path: Path, pid: Optional[int] = None) -> Path:
    """The temp sibling this module writes before renaming onto `path`.

    A SIBLING, never a file in a temp directory — see the module docstring:
    `os.replace` degrades to a non-atomic copy across filesystems, which would
    silently reinstate the window this module closes.
    """
    p = int(os.getpid() if pid is None else pid)
    return path.with_name(f"{path.name}{TMP_SUFFIX}.{p}")


def is_temp_artefact(path: Union[str, Path]) -> bool:
    """True for a name this module would have written as an in-progress temp.

    Exposed so a consumer that walks a run tree can EXCLUDE partials by name
    instead of guessing from size or mtime — both of which are properties a
    complete artefact can also have.
    """
    name = Path(path).name
    marker = f"{TMP_SUFFIX}."
    idx = name.rfind(marker)
    return idx > 0 and name[idx + len(marker):].isdigit()


@contextmanager
def writing(path: Union[str, Path], mode: str = "w",
            encoding: Optional[str] = "utf-8",
            **kwargs: Any) -> Iterator[Any]:
    """Open `path` for writing such that the final name appears only on success.

    The streaming form, for a writer that emits incrementally rather than
    handing over one finished string. On any exception the temp is removed and
    the exception propagates unchanged — a caller's error handling behaves
    exactly as it did before, it simply no longer leaves a carcass behind.

        with writing(report) as fh:
            fh.write(header)
            fh.write(body)          # dies here -> `report` does not exist

    `os.fsync` before the rename is what makes the guarantee survive a machine
    crash rather than merely a process death: without it the rename can reach
    the disk before the bytes do, and the final name would refer to a file
    whose content was never persisted. That is the same lie one layer down.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_name_for(dest)
    if "b" in mode:
        encoding = None
    fh = open(tmp, mode, encoding=encoding, **kwargs)
    try:
        yield fh
        fh.flush()
        os.fsync(fh.fileno())
    except BaseException:
        # BaseException, not Exception: SystemExit and KeyboardInterrupt are
        # two of the ways a step actually dies, and a partial artefact left by
        # a Ctrl-C is exactly as misleading as one left by a crash.
        fh.close()
        _discard(tmp)
        raise
    else:
        fh.close()
        os.replace(tmp, dest)


def _discard(tmp: Path) -> None:
    """Remove a temp, never masking the original failure with a cleanup error."""
    try:
        tmp.unlink()
    except OSError:
        pass


def write_text(path: Union[str, Path], data: str,
               encoding: str = "utf-8") -> Path:
    """`Path.write_text`, with the final name appearing only when complete.

    Signature-compatible on purpose: converting a call site is deleting
    `.write_text(` and calling this instead, so a reviewer can see that the
    payload did not change — this module is not the place to also alter what
    gets written.
    """
    dest = Path(path)
    with writing(dest, "w", encoding=encoding) as fh:
        fh.write(data)
    return dest


def write_bytes(path: Union[str, Path], data: bytes) -> Path:
    """`Path.write_bytes`, atomically."""
    dest = Path(path)
    with writing(dest, "wb", encoding=None) as fh:
        fh.write(data)
    return dest


def write_json(path: Union[str, Path], obj: Any, indent: int = 2,
               ensure_ascii: bool = False, sort_keys: bool = False) -> Path:
    """Serialise FIRST, then write, so a serialisation error writes nothing.

    Deliberately not `json.dump(obj, fh)`: dumping straight into the handle
    emits bytes as it walks the object, so a non-serialisable value halfway
    through leaves a truncated temp — recoverable here, but it also means the
    failure is discovered with a half-written file already on disk. Building
    the string first makes the whole artefact succeed or fail before anything
    is opened.
    """
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii,
                      sort_keys=sort_keys)
    if not text.endswith("\n"):
        text += "\n"
    return write_text(path, text)


if __name__ == "__main__":  # pragma: no cover - a smoke entry, not a gate
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
