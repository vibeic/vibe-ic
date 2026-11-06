"""programs/tests/_tree_write_audit.py -- run test nodes and record every write
they make under a root, including writes they undo before they finish.

WHY THIS EXISTS
===============
`suite_write_guard` compares two `git status` snapshots, and says so: "a write
made AND reverted inside a single test is invisible to a snapshot taken after
it". That is exactly the shape of a probe writer -- plant a file in the shipped
`programs/`, measure, unlink it in a `finally`. Nothing is left for a snapshot
to see, but every concurrent xdist worker that lists the tree in between sees
the file appear and vanish, and one of them reads it after the unlink
(`FileNotFoundError` in `test_upstream_mirror_is_pinned`, 8HD-8, 2026-09-28).

So this records the WRITE itself. A `sitecustomize` placed first on the child's
`PYTHONPATH` installs `sys.addaudithook` in the pytest child and in every Python
process it starts (the same mechanism as `step_input_scope.install_guard`).
CPython raises the `open` event from C for `open()`, `Path.write_text` and
`os.open` alike, and `os.remove`/`os.rename`/`os.mkdir`/`os.chmod`/
`shutil.rmtree`/... for the rest, whether the path is absolute, relative to the
cwd, or relative to a directory fd. Each event is tagged with
`PYTEST_CURRENT_TEST` ('' = collection).

WHAT IT DOES NOT SEE, stated so it is not read as a guarantee: a write made by a
non-Python process (a shell `>`, a compiled tool); a Python child started with
`-I`/`-S` or a scrubbed environment; a write under `__pycache__`/
`.pytest_cache` or to a `*.pyc` (bytecode churn, excluded on purpose); and a
BARE-NAME `os.open` (no directory component), which cannot be placed -- see the
fourth calibration below.

PATH RESOLUTION -- six calibrations, all measured:
  * with no `dir_fd`, CPython puts `dir_fd=-1` in every os-level event
    (`os.remove`, `os.rename`/`os.replace`, `os.mkdir`, `os.rmdir`,
    `os.chmod`, `os.chown`, `os.utime`, `os.symlink`, `os.link`); -1 means
    the cwd. Treating it as a descriptor dropped every cwd-relative change
    (review of PR fxprobe, 2026-09-28); only a descriptor >= 0 is joined.
  * `shutil.rmtree` removes entries by bare NAME relative to a directory fd;
    reading that name against the cwd invented deletions under the plugin root.
    The name is joined onto `/proc/self/fd/<dir_fd>` instead.
  * removing or renaming a SYMLINK acts on the entry, not its target. Resolving
    the whole path reported a tmp symlink farm's cleanup as the deletion of
    every file it pointed at. Entry-level events resolve only the parent.
  * an `O_TMPFILE` open names a directory and creates no entry in it, so it is
    not a write a reader can see (`tempfile.TemporaryFile()` with the cwd as
    its temp dir did this 45 times in one sweep).
  * `os.open` raises the `open` event WITHOUT its `dir_fd`, so a bare name from
    `os.open` cannot be placed: the runner's fd-bound publisher opens
    `.<name>.tmp.<pid>.<hex>` relative to a directory fd inside a tmp project,
    and reading it against the cwd reported it in the plugin root. A bare-name
    `os.open` is therefore NOT recorded -- the stated blind spot. A relative
    `os.open` WITH a directory component (`Path("programs/x").touch()`) is read
    against the cwd, and a bare name through builtin `open()` (mode is a
    string) has no directory fd to be relative to, so both ARE recorded.
  * the `os.mkdir` event fires before the call, and `mkdir(exist_ok=True)` on a
    directory that already exists changes nothing. Seven such events (tracked
    fixture dirs, `_shared/integration_fixtures`, the plugin root itself)
    came out of one sweep; a mkdir whose target already exists is not recorded.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

import _progress_run as _pr

_SITECUSTOMIZE = r'''
import os
import sys

_ROOT = os.environ.get("VIBEIC_TREE_WRITE_AUDIT_ROOT", "")
_LOG = os.environ.get("VIBEIC_TREE_WRITE_AUDIT_LOG", "")
# Functions whose writes are the HARNESS's, not the audited node's, named by
# IDENTITY: (resolved file, function name). A write made while one of them is
# on the stack is still logged, tagged `exempt`.
try:
    import json as _json
    _EXEMPT_IDS = {(os.path.realpath(f), n) for f, n in _json.loads(
        os.environ.get("VIBEIC_TREE_WRITE_AUDIT_EXEMPT", "") or "[]")}
except Exception:
    _EXEMPT_IDS = set()
_EXEMPT_NAMES = {n for _f, n in _EXEMPT_IDS}
_W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
# An O_TMPFILE open names a DIRECTORY and creates no entry in it: nothing a
# reader can list ever appears. Measured: `tempfile.TemporaryFile()` in a
# `python -c` child whose temp dir resolved to the cwd.
_TMPFILE = getattr(os, "O_TMPFILE", 0)
# event -> ((path arg, dir_fd arg or None, acts on the symlink TARGET), ...)
_EV = {
    "os.remove": ((0, 1, False),), "os.rename": ((0, 2, False), (1, 3, False)),
    "os.rmdir": ((0, 1, False),), "os.mkdir": ((0, 2, False),),
    "os.symlink": ((1, 2, False),), "os.link": ((1, 3, False),),
    "os.truncate": ((0, None, True),), "os.chmod": ((0, 2, True),),
    "os.chown": ((0, 3, True),), "os.utime": ((0, 3, True),),
    "shutil.copyfile": ((1, None, True),),
    "shutil.copytree": ((1, None, False),), "shutil.rmtree": ((0, None, False),),
    "shutil.move": ((0, None, False), (1, None, False)),
    "os.mkfifo": ((0, 2, False),), "os.mknod": ((0, 3, False),),
}
_busy = [False]


def _rel(p, dir_fd=None, follow=True):
    if isinstance(p, bytes):
        try:
            p = p.decode()
        except Exception:
            return None
    if not isinstance(p, (str, os.PathLike)):
        return None
    p = os.fspath(p)
    # dir_fd is a real descriptor only when >= 0. With no dir_fd CPython puts
    # -1 in the event, which means "relative to the cwd": that path falls
    # through to abspath() below, which reads the cwd at event time.
    if isinstance(dir_fd, int) and dir_fd >= 0 and not os.path.isabs(p):
        try:
            p = os.path.join(os.readlink("/proc/self/fd/%d" % dir_fd), p)
        except OSError:
            return None
    ap = os.path.abspath(p)
    if follow:
        rp = os.path.realpath(ap)
    else:
        rp = os.path.join(os.path.realpath(os.path.dirname(ap)),
                          os.path.basename(ap))
    root = _ROOT.rstrip(os.sep) + os.sep
    for q in (ap, rp):
        if q.startswith(root):
            rel = os.path.relpath(q, _ROOT)
            parts = rel.split(os.sep)
            if "__pycache__" in parts or ".pytest_cache" in parts \
                    or rel.endswith((".pyc", ".pyo")):
                return None
            return rel.replace(os.sep, "/")
    return None


def _exempt_caller():
    """The exempt function on the current stack, by identity, or None."""
    if not _EXEMPT_NAMES:
        return None
    f = sys._getframe(1)
    while f is not None:
        c = f.f_code
        if c.co_name in _EXEMPT_NAMES and \
                (os.path.realpath(c.co_filename), c.co_name) in _EXEMPT_IDS:
            return c.co_name
        f = f.f_back
    return None


def _log(ev, rel):
    import json
    exempt = _exempt_caller()
    fd = os.open(_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (json.dumps({
            "event": ev, "path": rel,
            "test": os.environ.get("PYTEST_CURRENT_TEST", ""),
            "exempt": exempt,
            "pid": os.getpid()}) + "\n").encode())
    finally:
        os.close(fd)


def _hook(ev, args):
    if _busy[0]:
        return
    try:
        _busy[0] = True
        if ev == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            if isinstance(path, int):
                return
            if _TMPFILE and isinstance(flags, int) \
                    and flags & _TMPFILE == _TMPFILE:
                return
            # `os.open` raises this event with mode None and NO dir_fd, so a
            # BARE name here may be relative to a directory fd rather than to
            # the cwd, and cannot be placed (see the module docstring). A
            # relative path WITH a directory component is read against the
            # cwd, as `Path("programs/x").touch()` means it.
            _p = os.fspath(path)
            if mode is None and not os.path.isabs(_p) \
                    and not os.path.dirname(_p):
                return
            if not ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                    or (isinstance(flags, int) and flags & _W)):
                return
            rel = _rel(path)
            if rel is not None:
                _log(ev, rel)
            return
        for i, fdi, follow in _EV.get(ev, ()):
            if i < len(args) and not isinstance(args[i], int):
                dfd = args[fdi] if fdi is not None and fdi < len(args) else None
                rel = _rel(args[i], dfd, follow)
                if rel is None:
                    continue
                # The event fires BEFORE the call. `mkdir(exist_ok=True)` on a
                # directory that is already there fails with EEXIST and changes
                # nothing, so it is not a write.
                if ev == "os.mkdir" and os.path.isdir(
                        os.path.join(_ROOT, rel)):
                    continue
                _log(ev, rel)
    except Exception:
        pass
    finally:
        _busy[0] = False


if _ROOT and _LOG:
    sys.addaudithook(_hook)
'''


@dataclass
class Audit:
    """What one audited child session did."""
    rc: int
    output: str
    #: nodeid -> "passed" | "failed" | "error" | "skipped", from the JUnit report
    outcomes: Dict[str, str] = field(default_factory=dict)
    #: one dict per write-class event under the root: event, path, test, pid
    events: List[dict] = field(default_factory=list)

    def writes_by(self, nodeid: str) -> List[dict]:
        """The writes `nodeid` made (`''`: the ones made during COLLECTION,
        which carry no test id). A write made inside a declared EXEMPT
        function -- the harness's own cleanup -- is not the node's, and is
        left out; the same write made by the node's own code is not."""
        return [e for e in self.events
                if not e.get("exempt")
                and (e["test"].split(" ")[0] if e["test"] else "") == nodeid]


def audit_env(root: Path, workdir: Path,
              exempt: Sequence[tuple] = ()) -> Dict[str, str]:
    """An environment whose Python processes record writes under `root`.
    `exempt`: ((file, function name), ...) whose writes are tagged exempt."""
    hook = workdir / "hook"
    hook.mkdir(parents=True, exist_ok=True)
    (hook / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    # The child is a separate session: nothing of the PARENT session's pytest
    # plumbing may reach it -- its xdist identity, its current-test tag (which
    # would attribute the child's writes to the parent's node), its addopts, or
    # its progress channel (the child would otherwise write events into the
    # landing supervisor's stream under the parent's nonce).
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT_TEST",
                                "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                                "VIBEIC_PYTEST_PROGRESS_",
                                "VIBEIC_PYTEST_RUNTIME_IDENTITY"))}
    # vibe-ic#1047: a broken third-party `pytest11` entry point on the host
    # (web3 on the landing host) must not decide what this child reports.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(hook)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["VIBEIC_TREE_WRITE_AUDIT_ROOT"] = str(Path(root).resolve())
    env["VIBEIC_TREE_WRITE_AUDIT_LOG"] = str(workdir / "events.jsonl")
    env["VIBEIC_TREE_WRITE_AUDIT_EXEMPT"] = json.dumps(
        [[str(Path(f).resolve()), str(n)] for f, n in exempt])
    return env


def read_events(workdir: Path) -> List[dict]:
    log = workdir / "events.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line]


def _junit_outcomes(xml_path: Path, plugin_root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not xml_path.is_file():
        return out
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        # classname is the dotted file path (+ class); rebuild the node id.
        parts = classname.split(".")
        for cut in range(len(parts), 0, -1):
            f = Path(*parts[:cut]).with_suffix(".py")
            if (plugin_root / f).is_file():
                nodeid = "::".join([f.as_posix()] + parts[cut:] + [name])
                break
        else:
            nodeid = f"{classname}::{name}"
        kinds = {child.tag for child in case}
        out[nodeid] = ("failed" if "failure" in kinds else
                       "error" if "error" in kinds else
                       "skipped" if "skipped" in kinds else "passed")
    return out


def run_nodes(nodeids: Sequence[str], *, plugin_root: Path,
              root: Path, exempt: Sequence[tuple] = ()) -> Audit:
    """Run `nodeids` (relative to `plugin_root`) in ONE child pytest session
    under the write audit, and return what it did.

    Bounded by PROGRESS (`_progress_run.run`), not by a wall clock: a child
    that stops making forward progress is killed and reported as not run, so
    every node reads "not run" and the caller's assertions go red by name.
    """
    with tempfile.TemporaryDirectory(prefix="tree_write_audit_") as tmp:
        work = Path(tmp)
        junit = work / "junit.xml"
        env = audit_env(root, work, exempt)
        try:
            r = _pr.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 f"--junitxml={junit}", *nodeids],
                cwd=str(plugin_root), env=env, capture_output=True, text=True)
            rc, output = r.returncode, (r.stdout or "") + (r.stderr or "")
        except _pr.Stalled as exc:
            rc, output = -1, f"STALLED, killed: {exc}"
        return Audit(rc=rc, output=output,
                     outcomes=_junit_outcomes(junit, plugin_root),
                     events=read_events(work))
