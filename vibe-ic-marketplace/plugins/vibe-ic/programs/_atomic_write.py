"""_atomic_write.py — the final filename appears only when the write finished.

vibe-ic#1082, adopted from OpenROAD-flow-scripts `flow/scripts/flow.sh:9`:

    trap 'mv "$LOG_DIR/$1.tmp.log" "$LOG_DIR/$1.log"' EXIT

Three lines of shell buy an invariant this repository has been bitten by twice:
**"the final filename exists" implies "the step ran to completion"** — by
construction, not by convention.

WHY IT MATTERS HERE
-------------------
A partially-written artefact under its final name is indistinguishable from a
complete one, and every downstream check that opens it inherits the lie. It is
the empty-tree shape one level down: the file exists, so the check proceeds, and
it proceeds over nothing.

The flow reads these artefacts to decide verdicts. `required_outputs` checks ask
"is the declared output there?", and today a step that died halfway through
`json.dump` answers YES. With an atomic write it answers NO, which is the true
statement about what happened — so those checks gain meaning they do not
currently have.

WHY `os.replace` AND NOT `shutil.move`
--------------------------------------
`os.replace` is atomic when source and destination are on the SAME filesystem,
which is why the temporary is created in the destination's own directory rather
than in `/tmp`. Across filesystems the rename degrades to copy-then-unlink and
the guarantee is lost silently — the exact failure mode this module exists to
remove — so the temporary's location is not a detail.

WHAT THIS DOES NOT PROMISE
--------------------------
Durability across power loss. There is no `fsync` here: the guarantee is that a
reader never observes a HALF-WRITTEN file under the final name, not that the
bytes have reached the platter. Adding `fsync` would cost a syscall per artefact
on a flow that writes thousands, for a property no consumer in this repository
tests. Stated rather than left to be assumed.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

__all__ = ["write_text_atomic", "write_json_atomic", "TMP_SUFFIX"]

#: Marker carried by every in-flight temporary. Chosen so a stray temporary is
#: identifiable as ours by a human reading a directory listing, and so a glob
#: for the final name never matches one (`*.json` does not match
#: `x.json.vibeic-tmp-1234`).
TMP_SUFFIX = ".vibeic-tmp"


def _write_atomic(path: Path, data: Union[str, bytes], encoding: Optional[str]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temporary lives in the DESTINATION directory, not the system temp
    # dir — see the module docstring: a cross-filesystem os.replace is not
    # atomic and fails open.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + TMP_SUFFIX + "-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w" if encoding else "wb",
                       **({"encoding": encoding} if encoding else {})) as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt or SystemExit
        # between mkstemp and replace would otherwise strand the temporary,
        # and a directory slowly filling with them is its own defect.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def write_text_atomic(path: Union[str, Path], text: str,
                      encoding: str = "utf-8") -> Path:
    """Write `text` so that `path` never exists in a partial state."""
    return _write_atomic(Path(path), text, encoding)


def write_json_atomic(path: Union[str, Path], obj: Any, *,
                      indent: int = 2, ensure_ascii: bool = False,
                      newline: bool = True) -> Path:
    """Serialise `obj` FIRST, then write atomically.

    The order is the point. `json.dump(obj, open(path, "w"))` truncates the file
    before it discovers that `obj` is not serialisable, which leaves a truncated
    artefact under the final name — the very shape this module removes. Building
    the string first means an unserialisable object raises with the previous
    file, if any, still intact.
    """
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)
    if newline:
        text += "\n"
    return write_text_atomic(path, text)
