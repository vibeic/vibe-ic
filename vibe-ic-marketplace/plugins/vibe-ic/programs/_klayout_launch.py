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

import json
import os
import posixpath
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _progress_run as _pr  # noqa: E402
import _watchdog as _wd  # noqa: E402
import _docker_watchdog as _dwd  # noqa: E402
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

__all__ = ["KLayoutRunner", "HostRunner", "ContainerRunner", "find_runner",
           "find_container_runner", "login_shell_argv"]

#: `_eda_pin.default_container_name()` IS this expression, plus the part
#: that was missing: the default half derives from the pinned digest
#: instead of being the shared literal `vibeic-eda`.  MEASURED 2026-09-07
#: on 8hd-3 -- the container holding that shared name was running 0.3.46
#: while the pin demanded 0.3.47, and a run that attached to it recorded
#: image provenance PASS about the wrong image.  `VIBEIC_EDA_CONTAINER` is
#: read exactly as before and still wins.
DEFAULT_CONTAINER = _pin.default_container_name()

_MOUNT_CACHE: Dict[str, List[Tuple[str, str]]] = {}


def _memory_bounded_argv(argv: Sequence[str], memory_limit_mb: int) -> str:
    """Enforce the per-tool virtual-memory ceiling before starting the tool."""
    limit = int(memory_limit_mb)
    if limit <= 0 or not argv:
        raise ValueError("a positive memory ceiling and nonempty argv are required")
    return f"ulimit -v {limit * 1024} || exit 125; exec {shlex.join([str(a) for a in argv])}"


# ── The container's LOGIN shell, with the profile's words kept off stdout ───
# Every command a `ContainerRunner` starts runs in the container's login shell
# (`bash -l`), because that is where the image puts its tools: PATH,
# PYTHONPATH, LD_LIBRARY_PATH and the PDK variables come from its login
# profile. The same profile PRINTS, and a login shell runs it on the command's
# own stdout. MEASURED on vibeic-eda 0.3.85, `bash -lc 'echo MARK'`:
#
#     [INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin:...
#     [INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12/...
#     MARK
#
# Every caller that parses stdout then read those words as its tool's data:
# byte-identical PDK antenna decks were reported as a "deck digest mismatch",
# a `*.lyt` listing grew two phantom technology files, and caller after caller
# grew its own `[INFO]`-line filter. The words are stopped HERE, at the one
# place the login shell is started, so no caller has to remember to filter.
#
# HOW: a POSIX launcher copies the real stdout to fd 3 and starts the SAME
# `bash -lc <cmd>` as before with fd 1 on /dev/null; the command's first act
# (`_UNPARK_STDOUT`) takes fd 1 back and closes fd 3, so the tool starts with
# exactly the descriptors it always had. Nothing about login startup is
# re-implemented -- bash still decides which profile files it reads -- so the
# environment the tools get is the one they got before. The profile's STDERR
# is left alone: a broken profile stays diagnosable. Image-agnostic by
# construction: `IIC_OSIC_TOOLS_QUIET` (the knob `_container_exec.exec_argv`
# passes) silences the two echoes one image guards on it, whereas this
# discards whatever any login profile writes to stdout.
_PARK_STDOUT = 'exec 3>&1; exec "$0" "$@" >/dev/null'
_UNPARK_STDOUT = "exec 1>&3 3>&-; "


def _parked_login_argv(container: str, script: str) -> List[str]:
    """`docker exec` argv running `script` in `container`'s login shell with
    stdout still PARKED on fd 3. `script` must unpark it (`_UNPARK_STDOUT`)
    before the output that belongs to the caller -- directly, or in a shell it
    `exec`s, which is how the supervised route keeps its identity stamp and
    nested login shell quiet too."""
    return _ce.docker_exec_argv(container, "sh", "-c", _PARK_STDOUT,
                                "bash", "-lc", script)


def login_shell_argv(container: str, cmd: str) -> List[str]:
    """`docker exec` argv running `cmd` in `container`'s login shell, with
    `cmd`'s stdout carrying `cmd`'s output and nothing the profile printed."""
    return _parked_login_argv(container, _UNPARK_STDOUT + cmd)


def host_read_bytes(path) -> Optional[bytes]:
    """The bytes of a HOST file, or None when it cannot be read."""
    try:
        return Path(str(path)).read_bytes()
    except OSError:
        return None


def host_list_files(directory, suffix: str) -> Optional[List[str]]:
    """Regular HOST files directly inside `directory` ending in `suffix`."""
    try:
        return sorted(str(p) for p in Path(str(directory)).iterdir()
                      if p.name.endswith(suffix) and p.is_file())
    except OSError:
        return None


def host_list_tree(directory) -> Optional[List[str]]:
    """Every regular HOST file under `directory`, recursively (links followed)."""
    root = Path(str(directory))
    if not root.is_dir():
        return None
    out: List[str] = []
    try:
        for base, _dirs, files in os.walk(root, followlinks=True):
            out.extend(str(Path(base) / f) for f in files
                       if (Path(base) / f).is_file())
    except OSError:
        return None
    return sorted(out)


def image_tree_overlays(trees: Sequence[str], mount_destinations: Sequence[str],
                        changed_paths: Sequence[str]) -> List[str]:
    """Why the bytes under `trees` inside a container may NOT be its image's.

    A container shows its image's bytes at a path only when no mount sits at,
    above or below that path and its writable layer changed nothing at or below
    it. `mount_destinations` are the container's bind/volume/tmpfs targets
    (`docker inspect`), `changed_paths` the paths `docker diff` lists. Pass a
    tree both as named and as resolved: a symlinked tree is read through its
    target. Empty = nothing overlays the image bytes.
    """
    out: List[str] = []
    for tree in dict.fromkeys(posixpath.normpath(t) for t in trees if t):
        for dst in mount_destinations:
            dst = posixpath.normpath(dst)
            if (tree == dst or tree.startswith(dst.rstrip("/") + "/")
                    or dst.startswith(tree + "/")):
                out.append(f"mount {dst} overlays {tree}")
        for changed in changed_paths:
            changed = posixpath.normpath(changed)
            if changed == tree or changed.startswith(tree + "/"):
                out.append(f"writable-layer change {changed} under {tree}")
    return out


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

    # ── Running something that is NOT a KLayout batch script ────────────────
    # A PDK ships its seal-ring / filler generators as ordinary `python3 <script>
    # --opt ...` CLIs that `import pya` (this is how LibreLane invokes them:
    # `KLayout.SealRing.run_generic` builds exactly such an argv). They must run
    # in the SAME environment KLayout lives in, which is what this class already
    # resolves — but not through `-r`, because their argv is their own.
    #
    # Paths are NOT translated here. The caller decides which arguments are
    # project paths (translate with `cpath`) and which are already environment-
    # native — a PDK under /foss/pdks inside the container has no host
    # counterpart, so translating it would corrupt a perfectly valid path.
    def run_argv(self, argv: Sequence[str], env: Dict[str, str],
                 *, timeout: int = 1800) -> Tuple[int, str, str]:
        raise NotImplementedError

    def run_argv_supervised(self, argv: Sequence[str], env: Dict[str, str], *,
                            stall_grace_s: float, memory_limit_mb: int,
                            progress_paths=()) -> _wd.SupervisedResult:
        """Run a long tool with progress supervision and an address-space cap."""
        raise NotImplementedError

    def exists(self, path) -> bool:
        """True when `path` is a readable file IN THIS RUNNER'S environment."""
        return Path(str(path)).is_file()

    # A PDK deck the tool will execute is identified by the bytes THIS RUNNER'S
    # KLayout reads, not by a same-named file on some other filesystem. These
    # two readers answer from the runner's own environment and return None
    # when that environment cannot answer, never a guess.
    def read_bytes(self, path) -> Optional[bytes]:
        """The bytes of `path` as this runner's KLayout would read them."""
        return host_read_bytes(path)

    def list_files(self, directory, suffix: str) -> Optional[List[str]]:
        """Regular files directly inside `directory` ending in `suffix`."""
        return host_list_files(directory, suffix)

    def list_tree(self, directory) -> Optional[List[str]]:
        """Every regular file under `directory`, recursively."""
        return host_list_tree(directory)

    def klayout_bin(self) -> str:
        """The KLayout GUI-class binary, for callers that need its own CLI
        (`-n <tech>`, `-rd k=v`). NOT `self._bin`: a host runner may have
        resolved `strmrun`, which is a script runner and accepts neither."""
        return shutil.which("klayout") or "klayout"


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

    def run_argv(self, argv, env, *, timeout=1800):
        full = dict(os.environ)
        full.setdefault("QT_QPA_PLATFORM", "offscreen")
        full.update({k: str(v) for k, v in env.items()})
        try:
            cp = subprocess.run([str(a) for a in argv], env=full,
                                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s"
        except OSError as exc:
            return 127, "", f"launch failed: {exc}"
        return cp.returncode, cp.stdout or "", cp.stderr or ""

    def run_argv_supervised(self, argv, env, *, stall_grace_s,
                            memory_limit_mb, progress_paths=()):
        full = dict(os.environ)
        full.setdefault("QT_QPA_PLATFORM", "offscreen")
        full.update({k: str(v) for k, v in env.items()})
        cmd = ["bash", "-c", _memory_bounded_argv(argv, memory_limit_mb)]
        return _wd.run_host_supervised(cmd, env=full,
                                        stall_grace_s=stall_grace_s,
                                        progress_paths=progress_paths)


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
            cp = subprocess.run(login_shell_argv(self._c, cmd),
                                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"klayout (container) timed out after {timeout}s"
        except OSError as exc:
            return 127, "", f"docker exec failed: {exc}"
        return cp.returncode, cp.stdout or "", cp.stderr or ""

    def run_argv(self, argv, env, *, timeout=1800):
        exports = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items())
        cmd = "export QT_QPA_PLATFORM=offscreen && "
        if exports:
            cmd += f"export {exports} && "
        cmd += " ".join(shlex.quote(str(a)) for a in argv)
        try:
            cp = subprocess.run(login_shell_argv(self._c, cmd),
                                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"command (container) timed out after {timeout}s"
        except OSError as exc:
            return 127, "", f"docker exec failed: {exc}"
        return cp.returncode, cp.stdout or "", cp.stderr or ""

    def run_argv_supervised(self, argv, env, *, stall_grace_s,
                            memory_limit_mb, progress_paths=()):
        exports = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items())
        # The watchdog wraps `cmd` in its identity stamp and a nested
        # `exec bash -lc`, both run with stdout still parked (see
        # `_parked_login_argv`); `cmd` itself unparks it, so the stamp shell,
        # BOTH login profiles and nothing else stay off the tool's stdout.
        cmd = _UNPARK_STDOUT + "export QT_QPA_PLATFORM=offscreen && "
        if exports:
            cmd += f"export {exports} && "
        cmd += _memory_bounded_argv(argv, memory_limit_mb)

        def raw_exec(container, probe, timeout=30):
            try:
                cp = subprocess.run(
                    login_shell_argv(container, probe),
                    capture_output=True, text=True, timeout=timeout)
                return cp.returncode, cp.stdout or "", cp.stderr or ""
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 124, "", f"docker watchdog probe failed: {exc}"

        start = time.monotonic()
        rc, out, err = _dwd.run_docker_supervised(
            self._c, cmd, str(argv[0]), docker_exec_raw=raw_exec,
            exec_argv=_parked_login_argv,
            progress_paths=progress_paths, stall_grace_s=stall_grace_s,
            poll_s=max(0.25, min(_wd.DEFAULT_POLL_S, stall_grace_s / 4)))
        outcome = "stalled" if rc == _wd.RC_STALLED else "natural"
        return _wd.SupervisedResult(
            rc, out, err, outcome, time.monotonic() - start,
            supervision={"watchdog": "docker_identity_stamped",
                         "stall_grace_s": stall_grace_s,
                         "progress_paths": [str(p) for p in progress_paths]})

    def klayout_bin(self) -> str:
        return "klayout"

    def _exec_bytes(self, *argv: str) -> Optional[bytes]:
        """stdout of `argv` run DIRECTLY in the container, or None.

        No shell, and above all no LOGIN shell: the image's profile prints
        `[INFO] Final PATH variable: ...` banners on stdout. MEASURED on the
        IC-die run (vibeic-eda 0.3.85): a positional parse of
        `bash -lc "sha256sum <parent> <rule>"` read those banner words as the
        two digests, so byte-identical PDK decks were reported as differing
        and Step 26 was never measured.
        """
        try:
            cp = subprocess.run(_ce.docker_exec_argv(self._c, *argv),
                                capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        return cp.stdout if cp.returncode == 0 else None

    def read_bytes(self, path):
        return self._exec_bytes("cat", "--", str(path))

    def list_files(self, directory, suffix):
        out = self._exec_bytes("find", "-L", str(directory), "-mindepth", "1",
                               "-maxdepth", "1", "-type", "f",
                               "-name", f"*{suffix}", "-print0")
        if out is None:
            return None
        return sorted(p.decode("utf-8", "surrogateescape")
                      for p in out.split(b"\0") if p)

    def list_tree(self, directory):
        out = self._exec_bytes("find", "-L", str(directory), "-type", "f",
                               "-print0")
        if out is None:
            return None
        return sorted(p.decode("utf-8", "surrogateescape")
                      for p in out.split(b"\0") if p)

    def image_id(self) -> Tuple[Optional[str], str]:
        """`(image_id, why_not)` of the image this container is running."""
        return _pin.container_image_id(self._c)

    def image_tree_proof(self, tree) -> Tuple[bool, str, Dict[str, object]]:
        """`(proven, why_not, record)`: are the bytes under `tree` the image's?

        A matching image id names the image, not the bytes a process in the
        container reads: a bind mount / volume / tmpfs at, above or below the
        tree, or an edit in the container's writable layer, replaces them
        while `.Image` stays the same. Proven only when `docker inspect`
        (mounts, tmpfs) and `docker diff` both answer and nothing overlays the
        tree as named or as resolved inside the container. Any unanswerable
        probe is "not proven", never "proven".
        """
        record: Dict[str, object] = {"guest_tree": str(tree)}
        real = self._exec_bytes("readlink", "-f", "--", str(tree))
        real_path = real.decode("utf-8", "surrogateescape").strip() if real else ""
        if not real_path.startswith("/"):
            return False, f"{tree} does not resolve inside {self._c}", record
        record["guest_tree_resolved"] = real_path
        try:
            ins = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{json .Mounts}}\t{{json .HostConfig.Tmpfs}}", self._c],
                capture_output=True, text=True, timeout=30)
            dif = subprocess.run(["docker", "diff", self._c],
                                 capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"container mounts/diff unanswerable: {exc}", record
        if ins.returncode != 0 or dif.returncode != 0:
            return False, (f"docker inspect/diff of {self._c} failed "
                           f"(rc {ins.returncode}/{dif.returncode})"), record
        try:
            mounts_json, tmpfs_json = ins.stdout.strip().split("\t", 1)
            mounts = json.loads(mounts_json) or []
            tmpfs = json.loads(tmpfs_json) or {}
            destinations = [str(m["Destination"]) for m in mounts]
            destinations += [str(d) for d in tmpfs]
        except (ValueError, KeyError, TypeError) as exc:
            return False, f"docker inspect of {self._c} is unreadable: {exc}", record
        # `docker diff` prints one "<A|C|D> <path>" per changed path.
        changed = [ln[2:] for ln in dif.stdout.splitlines()
                   if len(ln) > 2 and ln[0] in "ACD" and ln[1] == " "]
        record.update(mounts_checked=len(destinations),
                      writable_layer_changes_checked=len(changed))
        overlays = image_tree_overlays([str(tree), real_path], destinations,
                                       changed)
        if overlays:
            record["overlays"] = overlays
            return False, ("the image-bound tree is not the image's bytes in "
                           f"{self._c}: " + "; ".join(overlays)), record
        return True, "", record

    def exists(self, path):
        try:
            cp = _pr.run_best_effort(
                _ce.docker_exec_argv(self._c, "test", "-f", str(path)),
                capture_output=True, text=True)
            return cp.returncode == 0
        except Exception:                                    # noqa: BLE001
            return False


def _container_has_klayout(container: str) -> bool:
    try:
        cp = _pr.run_best_effort(
            login_shell_argv(container, "command -v klayout >/dev/null 2>&1"),
            capture_output=True, text=True)
        return cp.returncode == 0
    except Exception:                                        # noqa: BLE001
        return False


#: The run's OWN receipt of where its tools ran. `container_image_provenance`
#: writes it and records the container NAME under "container".
CONTAINER_IMAGE_REL = "reports/container_image.json"


def container_the_run_recorded(project) -> Optional[str]:
    """The container THIS RUN used, from its own receipt, or None.

    THE ONE RESOLVER, and it exists because two invocations of one gate answered
    differently on one host seconds apart. MEASURED on the SLT53D S arm: the
    phase-3 runner dispatched `gds_xor_check --container real-ic-arm-eda` and the
    XOR ran -- runner {"kind": "container", "detail": "real-ic-arm-eda:klayout"},
    verdict PASS, 0 design-layer differences across 46 layers. Seconds later the
    completion audit evaluated the SAME gate through the flow's static clause,
    which carries no `--container` because a per-host container name cannot be
    written into the yaml; `find_runner(None)` fell through to
    `DEFAULT_CONTAINER` -- a DIFFERENT container that does not mount that project
    -- and the gate said, correctly for what it was given, "no KLayout runner
    reaches this project". The audit then published that answer over the
    producer's measurement.

    The durable identity is the run's own record, not the pinned default name:
    `reports/container_image.json` is written by the run that used the container
    and names it. So a caller with no explicit `--container` asks the RUN which
    container it used before falling back to a name that is merely conventional.
    """
    try:
        doc = json.loads(
            (Path(project) / CONTAINER_IMAGE_REL).read_text(errors="replace"))
    except (OSError, ValueError, TypeError):
        return None
    name = doc.get("container") if isinstance(doc, dict) else None
    return str(name).strip() or None if isinstance(name, str) else None


def find_runner(container: Optional[str] = None,
                project=None) -> Optional[KLayoutRunner]:
    """Resolve a KLayout batch runner, host first then container.

    Returns None when neither is available — the caller MUST then emit a named,
    disclosed skip. Never silently succeed on a missing checker.

    `project`, when given, lets the run's OWN container receipt answer before the
    pinned default name does — see :func:`container_the_run_recorded` for the
    measurement that made this necessary. `container` still wins: an explicit
    argument is the caller stating which container it means.
    """
    if os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT"):
        # Test hook: proves the honest-degrade path without uninstalling
        # KLayout. Only ever set by the gate's own regression tests.
        return None
    for cand, flags in (("strmrun", ()), ("klayout", ("-zz", "-b", "-r"))):
        found = shutil.which(cand)
        if found:
            return HostRunner(found, flags)
    return find_container_runner(container, project=project)


def find_container_runner(container: Optional[str] = None,
                          project=None) -> Optional["ContainerRunner"]:
    """The CONTAINER half of :func:`find_runner`, with no host fallback.

    For a caller whose input lives INSIDE an image -- a PDK tree bound to the
    image the run used -- a host KLayout is not a substitute: it could only
    read some other copy of that tree. Same resolution order and the same
    test hook as :func:`find_runner`.
    """
    if os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT"):
        return None
    if shutil.which("docker"):
        recorded = container_the_run_recorded(project) if project else None
        for name in (container, recorded, DEFAULT_CONTAINER):
            if name and _container_has_klayout(name):
                return ContainerRunner(name)
    return None


#: (root, subdir, name) triples already reported as "the override carries no
#: such engine", so a program that resolves the same engine repeatedly says it
#: once instead of once per call.
_ENV_MISS_REPORTED: set = set()


def _subdir_spellings(subdir: str) -> List[str]:
    """`subdir` plus the same directory name under the other separator style.

    The plugin names its program directories with UNDERSCORES (``metal_fill/``,
    ``gds_antenna/``) because they sit next to importable Python; the KLayout
    fork names the very same engines with HYPHENS (``metal-fill/``,
    ``gds-antenna/``, and likewise ``mp-color/``, ``perc-latchup/``,
    ``cmp-gradient/`` …). Neither convention is wrong and neither repository
    owns the other's layout, so the override accepts both rather than forcing a
    rename on one side. What the caller asked for is always tried first.
    """
    out = [subdir]
    for alt in (subdir.replace("_", "-"), subdir.replace("-", "_")):
        if alt not in out:
            out.append(alt)
    return out


def find_engine(subdir: str, name: str) -> Optional[Path]:
    """Locate a KLayout-fork engine script.

    Resolution order (first hit wins):
      1. ``$VIBEIC_KLAYOUT_TOOLS/<subdir>/<name>`` — a fork checkout / a newer
         engine baked into the container image, which OVERRIDES the vendored copy.
         ``<subdir>`` is tried in both separator spellings (see
         :func:`_subdir_spellings`), because the fork's own directory names use
         hyphens and every caller here passes the underscored plugin spelling;
      2. ``<programs>/<subdir>/<name>`` — the copy vendored into the plugin, so a
         clean install can reach the capability with no extra setup.

    When the override IS set but carries no such engine, falling back to the
    vendored copy is correct — doing it *silently* is not. A silent fall-through
    is indistinguishable from the override having worked, which is precisely how
    the spelling mismatch above survived unnoticed, so the miss is named on
    stderr (once per root/engine) and the fallback still happens.
    """
    env = os.environ.get("VIBEIC_KLAYOUT_TOOLS")
    env_cands: List[Path] = []
    if env:
        env_cands = [Path(env) / s / name for s in _subdir_spellings(subdir)]
    for c in env_cands:
        if c.is_file():
            return c
    if env_cands:
        key = (str(env), subdir, name)
        if key not in _ENV_MISS_REPORTED:
            _ENV_MISS_REPORTED.add(key)
            tried = ", ".join(str(c) for c in env_cands)
            print(f"[klayout-engine] VIBEIC_KLAYOUT_TOOLS={env} carries no "
                  f"{subdir}/{name} (tried: {tried}) — falling back to the "
                  f"vendored copy; the override is NOT in effect for this engine",
                  file=sys.stderr)
    vendored = Path(__file__).resolve().parent / subdir / name
    return vendored if vendored.is_file() else None
