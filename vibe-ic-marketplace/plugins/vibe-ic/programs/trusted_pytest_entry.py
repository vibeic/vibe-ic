#!/usr/bin/env python3
"""Isolated pytest entry for the protected landing runtime.

Invoke this file with ``python3 -I``.  The isolated interpreter imports pytest
from the digest-pinned runner image, then loads the protected progress plugin
by exact path.  The subject cwd never participates in either import.  A
canonical identity record travels through the plugin's private semantic stream
so the parent can prove what actually executed, not merely what argv named.

THE HOST LANE
=============
``-I`` implies ``-s``, so the USER site directory is suppressed.  That is the
property this file exists for on a pinned-image host, and it is fatal on a host
whose pytest lives only there: ``import pytest`` raises, this entry refuses, and
the child dies before emitting one lifecycle event.  Measured on the landing
host at 7c376e348, the repo-tools arm alone: ``asked 40 recorded 0 NORECORD
40``, aggregate INCOMPLETE, zero junit cases.  Landing was impossible on any
host of the fleet.

``VIBEIC_TRUSTED_PYTEST_SITE`` opens the explicitly-named directories for that
host — one, or several separated by ``os.pathsep`` in the order they should
answer, because a runner's import closure is not always one directory's worth of
modules (MEASURED on this fleet: ``pygments`` lives in a different site
directory from ``pytest``) — and nothing else changes:

  * it is OPT-IN, never derived by default.  A silent fallback to the host's
    own site directory would dissolve the digest-pinned guarantee on every host
    at once, which is making the check pass by deleting what it checks.  The
    value ``auto`` asks for the non-isolated interpreter's user site directory
    to be DERIVED, and is still an explicit act by the caller.
  * it is resolved strict and refused by the SAME ``_under(resolved, subject)``
    / ``_under(resolved, programs)`` checks the module identities go through, so
    the subject checkout cannot become the runtime by naming itself.
  * every file it resolves is still raw-attested below.  ``sys.flags.isolated``
    still keeps the subject cwd off ``sys.path``, so the property this entry
    exists to guarantee survives the lane.

INSERTED AT POSITION 0, NOT APPENDED.  Measured: appending mixes user-site
pure-Python packages against the system's C extensions and dies in the mismatch
(cffi 2.0.0 against _cffi_backend 1.15.7).  Position 0 makes the named
directory answer first and consistently for its whole dependency closure.

``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` IS REQUIRED WITH THE LANE.  Restoring the
user site directory restores its ``pytest11`` entry points too, and on this
fleet one of them takes the session down at collection, which is the defect
``gatekeeper-land.sh:520-528`` documents.  The lane therefore REFUSES without
the token rather than trusting a caller to have set it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence


IDENTITY_ENV = "VIBEIC_PYTEST_RUNTIME_IDENTITY"
PROGRESS_PLUGIN_NAME = "_vibeic_protected_pytest_progress"
HOST_SITE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"
HOST_SITE_AUTO = "auto"
AUTOLOAD_ENV = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"


class Refusal(RuntimeError):
    pass


def _raw_identity(path: Path, label: str) -> dict[str, object]:
    try:
        lexical = path.absolute()
        before = lexical.lstat()
        if (not stat.S_ISREG(before.st_mode) or lexical.is_symlink()
                or before.st_nlink != 1):
            raise Refusal(f"{label} is not a single-link regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lexical, flags)
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            held = os.fstat(fd)
        finally:
            os.close(fd)
        after = lexical.lstat()
    except OSError as exc:
        raise Refusal(f"cannot raw-attest {label}: {exc}") from exc
    identity = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
                           st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if identity(before) != identity(held) or identity(before) != identity(after):
        raise Refusal(f"{label} changed while raw-attested")
    return {
        "path": str(lexical.resolve(strict=True)),
        "sha256": digest.hexdigest(),
        "size": size,
    }


def _module_file(module: ModuleType, label: str) -> Path:
    value = getattr(module, "__file__", None)
    if not isinstance(value, str) or not value:
        raise Refusal(f"{label} has no file identity")
    return Path(value)


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _strip_progress_plugin(argv: Sequence[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "-p":
            if index + 1 >= len(argv):
                raise Refusal("pytest -p has no plugin name")
            name = argv[index + 1]
            if name == "_pytest_progress_plugin":
                index += 2
                continue
            if name != "no:cacheprovider":
                raise Refusal(f"unreviewed pytest plugin request: {name!r}")
        out.append(argv[index])
        index += 1
    return out


def _derived_user_site() -> str:
    """The NON-isolated interpreter's user site directory.

    ``site`` is importable under ``-I`` and still computes this path; what
    ``-I`` removes is the path's PRESENCE on ``sys.path``, not the ability to
    name it.  So the derivation needs no second interpreter and cannot pick up
    a different one than the caller meant.
    """
    import site  # stdlib; the isolated interpreter still owns it

    derived = site.getusersitepackages()
    if isinstance(derived, (list, tuple)):
        derived = derived[0] if derived else ""
    if not isinstance(derived, str) or not derived:
        raise Refusal("the interpreter reports no user site directory to derive")
    return derived


def _host_lane(subject: Path, programs: Path) -> list[Path]:
    """Resolve, refuse and return the opted-in host site directories.

    Returning an EMPTY LIST is the pinned-image lane and the default: an unset
    variable changes nothing about this entry's behaviour.

    ONE VALUE MAY NAME MORE THAN ONE DIRECTORY, separated by ``os.pathsep``, in
    the order they should answer.  A single directory is the same value it
    always was and behaves identically, so nothing that names one changes.

    WHY A LIST AND NOT ONE DIRECTORY.  The lane's promise is that the isolated
    interpreter can resolve the RUNNER, and a runner is not one directory's
    worth of modules.  MEASURED on this fleet at 46db018669::

        pytest, _pytest, pluggy, iniconfig, packaging
                                 -> ~/.local/lib/python3.12/site-packages
        pygments                 -> /usr/lib/python3/dist-packages

    ``pytest`` imports ``pygments`` lazily, at terminal-writer time, so a lane
    naming only the first directory IMPORTS and then dies mid-session with
    ``No module named 'pygments'`` — the "imports and cannot report" shape
    ``landing_pytest_runtime_preflight`` exists to catch.  The system
    interpreter happens to survive it because ``-I`` suppresses only the USER
    site directory and keeps ``/usr/lib/python3/dist-packages``; an interpreter
    without that directory — a virtual environment, which is what a host that
    followed CONTRIBUTING may well be running the landing from — has no such
    luck and could not open the lane AT ALL, however precisely it named the
    directory the runner lives in.

    Every segment goes through the SAME resolution and the SAME two refusals as
    before.  Widening the value does not widen what may be named.
    """
    requested = os.environ.get(HOST_SITE_ENV)
    if requested is None or not requested.strip():
        return []
    segments = [item.strip() for item in requested.strip().split(os.pathsep)]
    if any(not item for item in segments):
        raise Refusal(f"{HOST_SITE_ENV} contains an empty directory segment")
    lanes: list[Path] = []
    for segment in segments:
        if segment == HOST_SITE_AUTO:
            segment = _derived_user_site()
        lane = Path(segment)
        if not lane.is_absolute():
            raise Refusal(f"{HOST_SITE_ENV} must name an absolute directory")
        try:
            resolved = lane.resolve(strict=True)
        except OSError as exc:
            raise Refusal(f"{HOST_SITE_ENV} does not resolve: {exc}") from exc
        if not resolved.is_dir():
            raise Refusal(f"{HOST_SITE_ENV} is not a directory: {resolved}")
        # The same two refusals the module identities go through, for the same
        # reason: a runtime the subject can name is a runtime the subject
        # controls.
        if _under(resolved, subject) or _under(resolved, programs):
            raise Refusal(
                f"{HOST_SITE_ENV} resolved inside the subject checkout")
        if resolved not in lanes:
            lanes.append(resolved)
    # ASSERTED, NOT ASSUMED. The lane restores these directories' pytest11 entry
    # points; on this fleet one of them raises at import and takes the whole
    # session down at collection, so the token is load-bearing exactly here.
    if os.environ.get(AUTOLOAD_ENV) != "1":
        raise Refusal(
            f"{HOST_SITE_ENV} requires {AUTOLOAD_ENV}=1 on the child: the lane "
            "restores these directories' entry-point plugins")
    return lanes


def run(argv: Sequence[str]) -> int:
    if not sys.flags.isolated or not sys.flags.ignore_environment:
        raise Refusal("trusted pytest entry requires python3 -I")
    programs = Path(__file__).resolve(strict=True).parent
    subject = Path.cwd().resolve(strict=True)
    if any(item in {"", "."} for item in sys.path):
        raise Refusal("isolated interpreter still exposes the subject cwd")

    # INSERTED AT POSITION 0, IN THE ORDER NAMED — see the module docstring for
    # the measurement that rules out appending.
    lanes = _host_lane(subject, programs)
    if lanes:
        sys.path[0:0] = [str(lane) for lane in lanes]

    import pytest  # type: ignore[import-not-found]  # image-owned dependency
    import _pytest  # type: ignore[import-not-found]
    import pluggy  # type: ignore[import-not-found]

    dependency_rows = []
    for name, module in (("pytest", pytest), ("_pytest", _pytest),
                         ("pluggy", pluggy)):
        module_path = _module_file(module, name).resolve(strict=True)
        if _under(module_path, subject) or _under(module_path, programs):
            raise Refusal(f"{name} resolved inside the subject checkout")
        dependency_rows.append({"name": name,
                                **_raw_identity(module_path, name)})

    plugin_path = programs / "_pytest_progress_plugin.py"
    plugin_identity = _raw_identity(plugin_path, "protected progress plugin")
    spec = importlib.util.spec_from_file_location(
        PROGRESS_PLUGIN_NAME, plugin_path)
    if spec is None or spec.loader is None:
        raise Refusal("protected progress plugin has no import loader")
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[PROGRESS_PLUGIN_NAME] = plugin
    spec.loader.exec_module(plugin)

    identity = {
        "schema": 1,
        "python": _raw_identity(
            Path(sys.executable).resolve(strict=True), "python executable"),
        "entry": _raw_identity(Path(__file__), "trusted pytest entry"),
        "plugin": plugin_identity,
        "modules": dependency_rows,
    }
    # THE LANE IS NOT ADDED TO THIS RECORD, and the reason is worth stating
    # because the first attempt did add it. `pytest_per_file_junit._runtime_identity`
    # validates the key set EXACTLY, so a new field is not extra information —
    # it is an invalid record. MEASURED: `asked 41 recorded 0 NORECORD 41`, every
    # file "invalid trusted pytest runtime identity". The same defect shape this
    # whole repair is about, produced by the repair.
    #
    # Nothing is lost. `dependency_rows` above already carries the RESOLVED
    # absolute path and sha256 of pytest, _pytest and pluggy, so which lane
    # answered is a fact the receipt states rather than asserts, and the landing
    # log carries the preflight's own one-line lane report as well.
    os.environ[IDENTITY_ENV] = json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False)
    return int(pytest.main(_strip_progress_plugin(list(argv)), plugins=[plugin]))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (ImportError, OSError, Refusal, ValueError, TypeError) as exc:
        print(f"[NORECORD] trusted pytest entry: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
