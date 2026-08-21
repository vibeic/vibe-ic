#!/usr/bin/env python3
"""_atomic_output.py — the final filename exists ONLY IF the step completed. #1082.

Adopted from OpenROAD-flow-scripts at `f9ec54a6de7b2bc69fd586015f6ebdab34eca69c`,
`flow/scripts/flow.sh:9`::

    trap 'mv "$LOG_DIR/$1.tmp.log" "$LOG_DIR/$1.log"' EXIT

Three lines of shell buy an invariant: the artefact is written under a temporary
name and reaches its final name only at the end, so *"the final filename exists"*
implies *"this step got that far"* — by construction rather than by convention.

MEASURED ON THIS COMMIT, BEFORE ANY OF THIS EXISTED
===================================================
`os.replace` appeared in **0** of the plugin's ~1078 programs, and **577** of them
name a `--json` / report output and write it straight to the final path. So the
invariant was not weakly held, it was absent.

And the failure is not theoretical. `open(path, 'w')` TRUNCATES at open, so a
process that dies between the open and the write leaves a file under the FINAL
name. Reproduced with a real `SIGKILL`:

    direct write, SIGKILL mid-write    exists=True   size=12  content='{"partial": '
    temp + rename, SIGKILL mid-write   exists=False  size=None

Twelve bytes of a JSON document, under the name a downstream consumer opens. That
is the empty-tree shape at the artefact level: the file exists, so the check
proceeds, and it proceeds over nothing.

WHERE WE DELIBERATELY DIFFER FROM ORFS, AND WHY COPYING IT WOULD BE WRONG
=========================================================================
Their trap is on ``EXIT``, which fires on **any** exit including a crash — so an
ORFS log is renamed into place even when the step failed. That is right for a
LOG: the log of a failed run is the most valuable log there is, and losing it
would be a regression.

It is wrong for a DECLARED OUTPUT. #1082's own words: *"A step that dies leaves no
file under the final name — so 'declared output missing' becomes an accurate
statement about what happened, and `required_outputs` checks gain meaning they do
not currently have."* A declared output renamed into place after a crash is
exactly the lie we are removing.

So there are two functions and they are not interchangeable:

    atomic_output(path)          rename on SUCCESS ONLY. For declared outputs.
                                 An exception removes the temp; a SIGKILL leaves
                                 the temp. Either way the final name is
                                 untouched.
    promote_orphan_temps(root)   the SUPERVISOR's half, called AFTER a step
                                 exits: promote a leftover temp whose final name
                                 is LOG-class, sweep every other. This is where
                                 ORFS's `trap … EXIT` actually belongs, and the
                                 first draft of this module got it wrong by
                                 putting it in the writer — see that function's
                                 docstring for the measurement that caught it.

WHAT ATOMICITY THIS DOES AND DOES NOT BUY
=========================================
``os.replace`` is atomic **within one filesystem**, so the temp file is created in
the SAME DIRECTORY as the target, never in ``/tmp``. A cross-filesystem rename
falls back to a copy, which is precisely the partial-write window this module
exists to close. :func:`_temp_for` enforces the same-directory rule and
``test_the_temp_file_is_a_sibling_of_the_target`` asserts it.

Bounds, stated because a bound nobody states is read as a guarantee:

* **SIGKILL / crash before the rename** — covered. Nothing is at the final name.
  This is the case that was measured above and the case that bit us twice.
* **Power loss** — covered as far as a single ``fsync`` of the file plus a
  best-effort ``fsync`` of the directory can cover it. Directory fsync is
  attempted and its failure is ignored, because some filesystems refuse it; a
  refusal must not turn a working writer into a broken one.
* **Two writers racing on one path** — NOT covered, and not attempted. The temp
  name carries the pid so they do not corrupt each other's temp, but the last
  ``os.replace`` wins and neither is "the" answer. That is a flow-ordering
  question, not an atomicity one.
* **A reader that opened the OLD inode before the rename** — keeps reading the old
  content, which is the correct and intended behaviour of a rename.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Optional, Union

_PathLike = Union[str, "os.PathLike[str]"]

#: The suffix a partial artefact carries while it is being written. Carries the
#: pid so two processes writing the same target do not share a temp file.
#: `atomic_output_tmp_glob` is the one place this shape is spelled, so a cleaner
#: or a scan cannot drift from the writer.
TMP_SUFFIX_FMT = ".tmp.{pid}"


def atomic_output_tmp_glob() -> str:
    """The glob that matches this module's temp files. One definition."""
    return "*.tmp.*"


def _temp_for(target: Path) -> Path:
    """The temp path for `target`, ALWAYS a sibling.

    Same directory is not a convenience: `os.replace` is only atomic inside one
    filesystem, and a `/tmp` temp renamed onto a project path degrades into a
    copy — reopening the partial-write window this module closes.
    """
    return target.with_name(target.name + TMP_SUFFIX_FMT.format(pid=os.getpid()))


def _fsync_dir(d: Path) -> None:
    """Best effort. A filesystem that refuses this must not break the writer."""
    try:
        fd = os.open(str(d), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextlib.contextmanager
def atomic_output(path: _PathLike, *, encoding: str = "utf-8") -> Iterator[Path]:
    """Yield a TEMP path; rename it onto `path` only if the block SUCCEEDS.

    For DECLARED OUTPUTS. On an exception the temp is removed and `path` is left
    exactly as it was — so a step that dies leaves no file under the final name
    and "declared output missing" becomes an accurate statement.

        with atomic_output(project / "reports/x.json") as tmp:
            tmp.write_text(json.dumps(report))

    The parent directory is created, because a writer that must mkdir first has
    a window where the directory exists and the artefact does not, and every
    caller was doing it anyway.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp_for(target)
    try:
        yield tmp
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt or a SystemExit must
        # not promote a partial artefact to its final name either.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    if not tmp.exists():
        raise FileNotFoundError(
            f"atomic_output({target}): the block completed without writing "
            f"{tmp.name}. Nothing was renamed, and the absence is deliberate: "
            f"a writer that produced no bytes must not leave a final name behind.")
    _sync_and_replace(tmp, target)
    del encoding  # kept in the signature for symmetry with the write_* helpers


def _sync_and_replace(tmp: Path, target: Path) -> None:
    try:
        fd = os.open(str(tmp), os.O_RDONLY)
    except OSError:
        fd = None
    if fd is not None:
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
    os.replace(str(tmp), str(target))
    _fsync_dir(target.parent)


def promote_orphan_temps(root: _PathLike, *,
                         log_suffixes: tuple = (".log", ".rpt.log", ".txt.log"),
                         ) -> dict:
    """The SUPERVISOR half of ORFS's trap. Call this AFTER a step exits.

    WHY THIS IS NOT A CONTEXT MANAGER, AND WHY THE FIRST VERSION OF IT WAS WRONG
    ==========================================================================
    ORFS keeps a failed step's log by renaming it from a shell ``trap … EXIT``.
    The first draft here translated that as a ``try/finally`` inside the writer —
    and it does not work, which the test caught rather than the review:

        atomic_output_keep_on_error(...)  ->  out.log MISSING after SIGKILL

    **A ``finally`` does not run in a process that received SIGKILL.** ORFS's trap
    works because it lives in the PARENT SHELL, which survives the step it
    supervised. The faithful translation is therefore supervisor-side, not
    writer-side, and no amount of care inside the dying process can substitute.

    So: the writer always uses :func:`atomic_output` (success-only, and proven
    SIGKILL-safe). The supervisor calls this afterwards and decides what a
    leftover temp MEANS:

        a temp whose final name is LOG-class  -> promoted. The log of a failed
                                                 run is the most valuable log
                                                 there is.
        every other leftover temp             -> swept. A declared output that
                                                 landed after a crash is the lie
                                                 #1082 exists to remove.

    Returns ``{"promoted": [...], "swept": [...]}`` — both lists, because a
    supervisor that reported only what it published would hide the artefacts it
    decided to destroy.
    """
    base = Path(root)
    out: dict = {"promoted": [], "swept": []}
    if not base.is_dir():
        return out
    for tmp in sorted(base.rglob(atomic_output_tmp_glob())):
        if not tmp.is_file():
            continue
        # `x.log.tmp.123` -> `x.log`; the suffix shape is TMP_SUFFIX_FMT's.
        final = tmp.with_name(tmp.name.rsplit(".tmp.", 1)[0])
        rel = tmp.relative_to(base).as_posix()
        if any(final.name.endswith(s) for s in log_suffixes):
            with contextlib.suppress(OSError):
                _sync_and_replace(tmp, final)
                out["promoted"].append(final.relative_to(base).as_posix())
        else:
            with contextlib.suppress(OSError):
                tmp.unlink()
                out["swept"].append(rel)
    return out


def atomic_write_text(path: _PathLike, text: str, *,
                      encoding: str = "utf-8") -> Path:
    """`Path.write_text` with the #1082 invariant. Returns the final path."""
    target = Path(path)
    with atomic_output(target) as tmp:
        tmp.write_text(text, encoding=encoding)
    return target


def atomic_write_json(path: _PathLike, obj: Any, *, indent: Optional[int] = 2,
                      sort_keys: bool = False, ensure_ascii: bool = True) -> Path:
    """Serialise FIRST, then write.

    The order matters and is the cheap half of the fix: `json.dumps` raising on
    an unserialisable value before anything is opened means the failure cannot
    leave a truncated file even without the rename. Callers that opened the file
    and then serialised into it had the window; this closes it twice.
    """
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys,
                      ensure_ascii=ensure_ascii) + "\n"
    return atomic_write_text(path, text)


def sweep_stale_temps(root: _PathLike) -> list:
    """Remove this module's temp files left by a killed writer. Returns the rels.

    A SIGKILL leaves the temp behind — which is the POINT, since the alternative
    is leaving it under the final name. But an accumulating litter of
    `*.tmp.<pid>` is its own confusion, so a runner may sweep them. Deliberately
    NOT automatic on import: deleting files as a side effect of importing a
    module is how a debugging session loses the evidence it was about to read.
    """
    base = Path(root)
    gone = []
    if not base.is_dir():
        return gone
    for p in sorted(base.rglob(atomic_output_tmp_glob())):
        if p.is_file():
            with contextlib.suppress(OSError):
                p.unlink()
                gone.append(p.relative_to(base).as_posix())
    return gone
