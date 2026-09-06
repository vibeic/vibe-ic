#!/usr/bin/env python3
"""_designs_root.py — the ONE answer to "which host directory does the EDA
container see, and under what container path?".

WHY THIS MODULE EXISTS
======================
Three shipped programs used to answer that question by looking for a MAGIC
DIRECTORY NAME inside the host path::

    host_root = Path(str(project).split(NAME)[0]) / NAME    # two analog drivers
    if NAME in str(h): ... Path.home() / NAME               # the yosys flattener

`NAME` was one developer's design-tree directory. On every other machine the
test `NAME in str(project)` is False, so the programs fell through to a
DIFFERENT root and emitted container paths that do not exist inside the
container — a wrong answer that renders exactly like a right one. Substituting
a different directory name would leave the same defect wearing new clothes: a
name is not a measurement.

The repo already answers this question properly, in
``benchmark/score_iverilog_tb.py``: the designs-root resolution LADDER, which
asks the CONTAINER which host directory it has mounted. That doctrine — and its
regression suite, ``programs/tests/test_designs_root_resolution_ladder.py`` —
is what this module now owns. The scorer delegates to it instead of keeping a
second copy, and the three sites above consume it instead of a directory name.

THE LADDER — relocated, not redesigned
======================================
  1. ``$VIBEIC_DESIGNS_HOST_ROOT`` — explicit; power users and CI.
  2. DERIVED FROM THE CALLER'S PROJECT. Ask the container which of its bind
     mounts CONTAINS the project and use that mount's ``Source``. The
     ``Destination`` is kept beside it, because users may mount the same tree
     at any container path: ``/foss/designs`` is a DEFAULT, never an
     assumption. When no mount contains the project the project directory
     itself is used — recorded under a DISTINCT basis, so a caller that must
     not guess can refuse it.
  3. Neither — ``host_root`` is None. We do NOT hard-exit and we do NOT invent
     a path: :func:`unresolved_status` returns a machine-readable
     needs-a-human-decision value for the driving agent to relay.

WHAT "I CANNOT TELL" LOOKS LIKE
===============================
An unanswerable question has "I cannot tell" as its honest answer, and that
answer must not render like a good one:

  * :class:`Resolution` exposes ``basis`` — ``explicit_env`` and
    ``container_mount`` are MEASURED; ``project_dir_fallback`` is a fallback
    and says so; ``undecided`` is None.
  * :attr:`Resolution.mount_root_is_measured` is the predicate a caller that is
    about to ``docker exec`` should require.
  * :func:`translate` returns a :class:`Translation` whose ``path`` is None
    (never the input path, never a guessed prefix) when no mount covers the
    file, with ``detail`` naming what was actually mounted.

chip-AGNOSTIC: no PDK, vendor, IC, project or directory-name literal.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

#: Rung 1 — the host directory the user bind-mounted into the EDA container.
HOST_ROOT_ENV = "VIBEIC_DESIGNS_HOST_ROOT"
#: The container-side destination, when the user states it rather than letting
#: the mount table speak.
CONT_ROOT_ENV = "VIBEIC_DESIGNS_CONT_ROOT"
#: The historical container destination. A DEFAULT for the offline branch a
#: caller opts into explicitly — never an assumption about a live container.
DEFAULT_CONT_ROOT = "/foss/designs"
#: The container a caller gets when it names none.  DERIVED FROM THE PINNED
#: DIGEST by `_eda_pin.default_container_name`, not the shared literal
#: `vibeic-eda`: MEASURED 2026-09-07 on 8hd-3, the container holding that shared
#: name was running 0.3.46 while the pin demanded 0.3.47, and a run that
#: attached to it recorded image provenance PASS about the wrong image.  A name
#: that carries the digest makes two different pins two different containers by
#: construction.  `VIBEIC_EDA_CONTAINER` still names one explicitly and is still
#: honoured -- it moves the NAME, never the digest requirement.
DEFAULT_CONTAINER = _pin.default_container_name()

ERROR_CODE = "DESIGNS_ROOT_UNRESOLVED"

# ---- how the root was reached ------------------------------------------------
BASIS_ENV = "explicit_env"              # the user stated it
BASIS_MOUNT = "container_mount"         # the container's own mount table said it
BASIS_PROJECT_FALLBACK = "project_dir_fallback"   # nothing mounted covers it
BASIS_UNDECIDED = "undecided"           # no project, no env — we cannot tell

#: The bases under which the root is a MEASUREMENT of the container rather than
#: a stand-in for one.
MEASURED_BASES = frozenset({BASIS_ENV, BASIS_MOUNT})

# ---- how a translation was reached -------------------------------------------
TR_MOUNT_PAIR = "container_mount_pair"
TR_EXPLICIT_DEST = "explicit_container_root_env"
TR_OFFLINE_DEFAULT = "offline_default_container_root"
TR_NONE = "unresolved"


class MountRootUnresolved(RuntimeError):
    """Neither the container's mount table nor an explicit setting can say how a
    host path is reachable inside the container.

    Carries the same structured status :func:`unresolved_status` returns, so a
    caller may either branch on a value or catch this — but never receive a
    plausible-looking path in place of an answer.
    """

    def __init__(self, status: dict):
        super().__init__(status.get("reason", ERROR_CODE))
        self.status = status


@dataclass(frozen=True)
class Resolution:
    """The host designs root, plus HOW it was reached and what was mounted."""

    host_root: Optional[Path]
    basis: str
    container: str
    mounts: Tuple[Tuple[Path, str], ...] = ()

    @property
    def resolved(self) -> bool:
        return self.host_root is not None

    @property
    def mount_root_is_measured(self) -> bool:
        """True only when the root came from the container or from the user.

        A caller about to build a path for ``docker exec`` must require this:
        under ``project_dir_fallback`` nothing has confirmed the container can
        see the tree at all.
        """
        return self.basis in MEASURED_BASES


@dataclass(frozen=True)
class Translation:
    """A host->container path, or an explicit refusal to invent one."""

    path: Optional[str]
    basis: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None


def container_mounts(container: str = DEFAULT_CONTAINER
                     ) -> List[Tuple[Path, str]]:
    """Resolved ``(host source, container destination)`` bind mounts.

    The destination is load-bearing: a host root discovered from ``Source``
    cannot safely be rewritten to the historical default, because users may
    mount the same tree at any container path.

    Returns ``[]`` when the table cannot be read (docker absent, container
    down, output unparsable). ``[]`` means "I could not look", never "there are
    no mounts" — every caller here keeps the two apart.
    """
    try:
        out = subprocess.check_output(["docker", "inspect", container],
                                      text=True, stderr=subprocess.DEVNULL,
                                      timeout=20)
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError,
            ValueError):
        return []
    if not data:
        return []
    mounts: List[Tuple[Path, str]] = []
    for m in (data[0].get("Mounts") or []):
        src = m.get("Source")
        dst = m.get("Destination")
        if src and dst:
            try:
                mounts.append((Path(src).resolve(), str(dst)))
            except OSError:
                pass
    return mounts


def mount_sources(container: str = DEFAULT_CONTAINER) -> List[Path]:
    """Host-side sources of the container's bind mounts. ``[]`` if unknowable."""
    return [src for src, _dst in container_mounts(container)]


def resolve_host_root(design_dir=None,
                      container: str = DEFAULT_CONTAINER,
                      *,
                      sources: Optional[Sequence[Path]] = None,
                      mounts: Optional[Sequence[Tuple[Path, str]]] = None,
                      warn: Optional[Callable[[str], None]] = None,
                      ) -> Resolution:
    """Walk the ladder. Never creates a directory, never raises, never guesses.

    ``sources`` / ``mounts`` let a caller inject an already-read mount table
    (and let a test pin one) instead of shelling out again.
    """
    pairs: Tuple[Tuple[Path, str], ...]
    if mounts is not None:
        pairs = tuple(mounts)
    elif sources is not None:
        pairs = ()
    else:
        pairs = tuple(container_mounts(container))
    srcs: List[Path] = (list(sources) if sources is not None
                        else [s for s, _d in pairs])

    # ---- 1. explicit env -------------------------------------------------
    raw = os.environ.get(HOST_ROOT_ENV)
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            return Resolution(p.resolve(), BASIS_ENV, container, pairs)
        if warn is not None:
            warn(raw)

    # ---- 2. derive from the caller's project -----------------------------
    if design_dir is not None:
        try:
            proj = Path(design_dir).resolve()
        except OSError:
            return Resolution(None, BASIS_UNDECIDED, container, pairs)
        # The mount that CONTAINS the project wins: translation then stays
        # correct for the whole tree, not just the project subdirectory.
        for src in srcs:
            if proj == src or src in proj.parents:
                return Resolution(src, BASIS_MOUNT, container, pairs)
        # Nothing mounted covers it (or the table could not be read). The
        # project directory is the user's own, already exists, and is the thing
        # the container needs to see — but NOTHING has confirmed it is visible,
        # so the basis records that this is a fallback.
        if proj.is_dir():
            return Resolution(proj, BASIS_PROJECT_FALLBACK, container, pairs)

    # ---- 3. undecidable --------------------------------------------------
    return Resolution(None, BASIS_UNDECIDED, container, pairs)


def _join(dst: str, rel: Path) -> str:
    return dst.rstrip("/") + ("/" + rel.as_posix() if rel.parts else "")


def translate(host_path,
              *,
              root: Optional[Path] = None,
              mounts: Optional[Sequence[Tuple[Path, str]]] = None,
              explicit_container_root: Optional[str] = None,
              offline_default: Optional[str] = None,
              ) -> Translation:
    """Host path -> the path that resolves inside the container.

    Order:
      * an explicitly configured destination (``explicit_container_root``)
        stays authoritative for CI and power users who deliberately decouple
        translation from docker inspection;
      * otherwise the exact ``Source``/``Destination`` pair docker reports,
        longest source prefix first (the rule the kernel applies to the visible
        namespace);
      * otherwise ``offline_default`` IF AND ONLY IF the caller named one —
        this is the documented offline branch, opted into by name.

    With no branch available the result's ``path`` is None. It is deliberately
    NOT the input path: handing a host path to ``docker exec`` is how an
    unreachable file produced "No such file or directory" from inside a
    container instead of a verdict from this program.
    """
    try:
        hp = Path(host_path).resolve()
    except OSError:
        hp = Path(host_path)

    if explicit_container_root and root is not None:
        try:
            rel = hp.relative_to(root)
        except ValueError:
            return Translation(
                None, TR_NONE,
                f"{hp} is outside the configured designs root {root}")
        return Translation(_join(explicit_container_root, rel),
                           TR_EXPLICIT_DEST)

    best: Optional[Tuple[int, str, Path]] = None
    for src, dst in (mounts or ()):
        try:
            rel = hp.relative_to(src)
        except ValueError:
            continue
        if best is None or len(src.parts) > best[0]:
            best = (len(src.parts), dst, rel)
    if best is not None:
        return Translation(_join(best[1], best[2]), TR_MOUNT_PAIR)

    if offline_default and root is not None:
        try:
            rel = hp.relative_to(root)
        except ValueError:
            return Translation(None, TR_NONE,
                               f"{hp} is outside the designs root {root}")
        return Translation(_join(offline_default, rel), TR_OFFLINE_DEFAULT)

    listing = ("\n".join(f"    {s} -> {d}" for s, d in (mounts or ()))
               or "    (none reported)")
    return Translation(
        None, TR_NONE,
        f"no bind mount covers {hp}. Mounts seen:\n{listing}")


def help_text(container: str = DEFAULT_CONTAINER) -> str:
    return (
        "Cannot tell which host directory the EDA container can see. "
        "Choose one:\n"
        "  (a) pass a project directory that lives under one of the "
        "container's bind mounts, so the root is derived from it "
        "automatically; or\n"
        f"  (b) export {HOST_ROOT_ENV}=<an EXISTING directory you have "
        f"bind-mounted into the '{container}' container> and "
        f"{CONT_ROOT_ENV}=<the path it is mounted at inside the container>.\n"
        "Nothing is created for you — the plugin never adds directories to "
        "your home directory."
    )


def unresolved_status(detail: str = "",
                      container: str = DEFAULT_CONTAINER) -> dict:
    """The structured 'a human must choose' status (ladder step 3).

    Deliberately a VALUE, not an exit: the caller is an AI agent that can
    surface the choice to the user. Prompting from here would break on a
    non-TTY; guessing would resurrect the defect this module exists to remove.
    """
    return {
        "verdict": "SKIP",
        "error_code": ERROR_CODE,
        "needs_user_decision": True,
        "reason": (detail + " " if detail else "") + help_text(container),
        "options": [
            {"id": "derive_from_project",
             "how": "invoke with a project/design directory"},
            {"id": "explicit_env",
             "how": f"export {HOST_ROOT_ENV}=<existing directory>"},
        ],
    }


def container_path(host_path, design_dir, container: str = DEFAULT_CONTAINER,
                   *, mounts: Optional[Sequence[Tuple[Path, str]]] = None,
                   ) -> Translation:
    """One call for a caller about to ``docker exec``: host path -> container
    path, or an honest refusal.

    No offline default is available through this entry point on purpose. A
    program that is about to run a tool inside the container must not be handed
    a path the container has not been shown to see.
    """
    pairs = list(container_mounts(container)) if mounts is None else list(mounts)
    res = resolve_host_root(design_dir, container, mounts=pairs)
    if not res.mount_root_is_measured:
        return Translation(
            None, TR_NONE,
            f"the host mount root for {Path(design_dir).resolve()} is not "
            f"measured (basis: {res.basis}).")
    return translate(host_path, root=res.host_root, mounts=pairs,
                     explicit_container_root=os.environ.get(CONT_ROOT_ENV))
