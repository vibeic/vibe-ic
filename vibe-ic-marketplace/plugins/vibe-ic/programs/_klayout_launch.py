#!/usr/bin/env python3
"""_klayout_launch.py — shared locator/launcher for KLayout batch scripts.

The KLayout-fork sign-off engines (GDS-geometry antenna deck, per-layer density
metal fill) are ordinary KLayout batch scripts driven by environment variables.
They must run wherever KLayout actually lives, which in this project is one of
two places:

  * on the HOST PATH (``strmrun``, or ``klayout -b -r``) — a developer box with a
    local KLayout build;
  * inside the EDA CONTAINER (``$VIBEIC_EDA_CONTAINER``, default ``vibeic-eda``) —
    the normal flow environment, where the host has no KLayout at all.

A naive host-only ``shutil.which("klayout")`` therefore reports "no KLayout" on
every real flow run, which would turn every geometry gate into a permanent skip.
This module resolves the runner for both cases and, for the container case,
translates host paths to their in-container equivalents via the bind mounts
(``docker inspect``) so the script, its inputs and its outputs all resolve.

chip/PDK-AGNOSTIC: no design, vendor or PDK literal appears here.

    runner = find_runner()
    if runner is None:
        ...            # caller emits a NAMED, DISCLOSED skip — never a bare PASS
    rc, out, err = runner.run(script, {"ANT_GDS": gds, ...},
                              path_keys=("ANT_GDS", "ANT_CONFIG", "ANT_OUT"))
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["KLayoutRunner", "HostRunner", "ContainerRunner", "find_runner"]

DEFAULT_CONTAINER = os.environ.get("VIBEIC_EDA_CONTAINER", "vibeic-eda")

_MOUNT_CACHE: Dict[str, List[Tuple[str, str]]] = {}


def _container_mounts(container: str) -> List[Tuple[str, str]]:
    """(host_src, container_dst) bind mounts of `container`, longest first.

    Mirrors phase3_one_shot_runner._container_mounts; duplicated here so a
    single gate program does not have to import the multi-thousand-line runner.
    """
    if container in _MOUNT_CACHE:
        return _MOUNT_CACHE[container]
    out: List[Tuple[str, str]] = []
    try:
        cp = subprocess.run(
            ["docker", "inspect", container, "--format",
             "{{range .Mounts}}{{.Source}}|{{.Destination}}\n{{end}}"],
            capture_output=True, text=True, timeout=15,
        )
        if cp.returncode == 0:
            for line in cp.stdout.splitlines():
                line = line.strip()
                if not line or "|" not in line:
                    continue
                src, dst = line.split("|", 1)
                if src and dst:
                    out.append((src.rstrip("/"), dst.rstrip("/")))
    except Exception:                                        # noqa: BLE001
        pass
    out.sort(key=lambda t: len(t[0]), reverse=True)
    _MOUNT_CACHE[container] = out
    return out


class KLayoutRunner:
    """A resolved way to execute a KLayout batch script."""

    kind = "none"
    detail = ""

    def cpath(self, host_path) -> str:
        return str(host_path)

    def covers(self, host_path) -> bool:
        """True when `host_path` is reachable by this runner."""
        return True

    def run(self, script, env: Dict[str, str], *,
            path_keys: Iterable[str] = (),
            timeout: int = 1800) -> Tuple[int, str, str]:
        raise NotImplementedError


class HostRunner(KLayoutRunner):
    kind = "host"

    def __init__(self, binary: str, flags: Sequence[str]):
        self._bin = binary
        self._flags = list(flags)
        self.detail = f"{binary} {' '.join(flags)}".strip()

    def run(self, script, env, *, path_keys=(), timeout=1800):
        full = dict(os.environ)
        full.setdefault("QT_QPA_PLATFORM", "offscreen")
        full.update({k: str(v) for k, v in env.items()})
        try:
            cp = subprocess.run([self._bin, *self._flags, str(script)],
                                env=full, capture_output=True, text=True,
                                timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"klayout timed out after {timeout}s"
        except OSError as exc:
            return 127, "", f"klayout launch failed: {exc}"
        return cp.returncode, cp.stdout or "", cp.stderr or ""


class ContainerRunner(KLayoutRunner):
    kind = "container"

    def __init__(self, container: str, binary: str = "klayout",
                 flags: Sequence[str] = ("-zz", "-b", "-r")):
        self._c = container
        self._bin = binary
        self._flags = list(flags)
        self.detail = f"{container}:{binary}"

    def cpath(self, host_path) -> str:
        p = str(host_path)
        if not p:
            return p
        for src, dst in _container_mounts(self._c):
            if p == src:
                return dst
            if p.startswith(src + "/"):
                return dst + p[len(src):]
        return p

    def covers(self, host_path) -> bool:
        p = str(host_path)
        if not p:
            return False
        return any(p == src or p.startswith(src + "/")
                   for src, _ in _container_mounts(self._c))

    def run(self, script, env, *, path_keys=(), timeout=1800):
        pk = set(path_keys)
        exports = " ".join(
            f"{k}={shlex.quote(self.cpath(v) if k in pk else str(v))}"
            for k, v in env.items())
        script_c = self.cpath(script)
        cmd = "export QT_QPA_PLATFORM=offscreen && "
        if exports:
            cmd += f"export {exports} && "
        cmd += f"{self._bin} {' '.join(self._flags)} {shlex.quote(script_c)}"
        try:
            cp = subprocess.run(["docker", "exec", self._c, "bash", "-lc", cmd],
                                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"klayout (container) timed out after {timeout}s"
        except OSError as exc:
            return 127, "", f"docker exec failed: {exc}"
        return cp.returncode, cp.stdout or "", cp.stderr or ""


def _container_has_klayout(container: str) -> bool:
    try:
        cp = subprocess.run(
            ["docker", "exec", container, "bash", "-lc",
             "command -v klayout >/dev/null 2>&1"],
            capture_output=True, text=True, timeout=30)
        return cp.returncode == 0
    except Exception:                                        # noqa: BLE001
        return False


def find_runner(container: Optional[str] = None) -> Optional[KLayoutRunner]:
    """Resolve a KLayout batch runner, host first then container.

    Returns None when neither is available — the caller MUST then emit a named,
    disclosed skip. Never silently succeed on a missing checker.
    """
    if os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT"):
        # Test hook: proves the honest-degrade path without uninstalling
        # KLayout. Only ever set by the gate's own regression tests.
        return None
    for cand, flags in (("strmrun", ()), ("klayout", ("-zz", "-b", "-r"))):
        found = shutil.which(cand)
        if found:
            return HostRunner(found, flags)
    if shutil.which("docker"):
        name = container or DEFAULT_CONTAINER
        if name and _container_has_klayout(name):
            return ContainerRunner(name)
    return None


def find_engine(subdir: str, name: str) -> Optional[Path]:
    """Locate a KLayout-fork engine script.

    Resolution order (first hit wins):
      1. ``$VIBEIC_KLAYOUT_TOOLS/<subdir>/<name>`` — a fork checkout / a newer
         engine baked into the container image, which OVERRIDES the vendored copy;
      2. ``<programs>/<subdir>/<name>`` — the copy vendored into the plugin, so a
         clean install can reach the capability with no extra setup.
    """
    env = os.environ.get("VIBEIC_KLAYOUT_TOOLS")
    cands: List[Path] = []
    if env:
        cands.append(Path(env) / subdir / name)
    cands.append(Path(__file__).resolve().parent / subdir / name)
    for c in cands:
        if c.is_file():
            return c
    return None
