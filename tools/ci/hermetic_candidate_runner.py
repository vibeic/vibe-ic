#!/usr/bin/env python3
"""Run one candidate-only EDA arm in the fixed, least-privilege image.

This helper deliberately has no total elapsed-time limit.  Liveness comes from
an exact finite-work protocol: the candidate must write canonical progress
records to stdout, prefixed by ``VIBEIC_PROGRESS ``.  Only completion of the
next parent-owned work unit renews the recording lease.  A malformed channel
or a lease with no semantic progress is NORECORD, never a test verdict.

The candidate container never sees a writable host bind.  It writes artefacts
to a per-run named Docker volume.  Only after Docker proves it stopped does a
separately inspected unprivileged exporter copy that volume into a private
transport directory; publication waits until both named containers and the
volume are removed and independently proved absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Sequence


SCHEMA = 1
#: THE PIN IS THE DIGEST.  THE REPOSITORY IS DEPLOYMENT CONFIGURATION.
#:
#: These are two different questions and they used to be one string.  The digest
#: names the bytes and is the identity: it is what makes a runtime immutable and
#: it is what every check below actually asserts.  The repository names a place
#: those bytes can be fetched from, and which place a given host can reach is a
#: fact about the network, not about the runtime.  MEASURED 2026-09-07: the same
#: image, distributed to five hosts, carries the SAME repo digest on every host
#: that pulled it, while its image Id differs by storage driver -- so the repo
#: digest is the thing to bind, and the repository half of it has to be
#: configurable or hosts that cannot reach the published registry cannot be
#: pinned at all.
#:
#: So: the digest is a literal here, in ONE place, and the repository comes from
#: ONE config point that defaults to the published repository.  A deployment
#: that serves the same bytes from elsewhere sets the env; it does NOT edit this
#: file, and it CANNOT change which bytes are demanded.
IMAGE_DIGEST = (
    "sha256:8c5694abdf5c269c1d9def5368704e0c4b51c869d1d9c9380e123e07657fe9eb"
)
IMAGE_REPO_DEFAULT = "ghcr.io/vibeic/vibeic-eda"
IMAGE_REPO_ENV = "VIBEIC_EDA_IMAGE_REPO"


def image_repo() -> str:
    """The repository half of the pinned reference.

    Deployment configuration, read from one env.  Empty or unset means the
    published repository.
    """
    return os.environ.get(IMAGE_REPO_ENV) or IMAGE_REPO_DEFAULT


def image_reference() -> str:
    """`<configured repo>@<pinned digest>` -- the only reference this runner uses."""
    return f"{image_repo()}@{IMAGE_DIGEST}"


#: Resolved once, at import, so that every check in this module and every
#: container it inspects are talking about the same string for the life of the
#: process.  `_image_profile` binds this against the image's own RepoDigests.
IMAGE = image_reference()
IMAGE_REPO_DIGEST = IMAGE
USER = "65534:65534"
PLATFORM = "linux/amd64"
WORKDIR = "/subject"
RUNTIME_ROOT = "/runtime"
PROGRESS_PREFIX = b"VIBEIC_PROGRESS "
TMPFS_OPTIONS = (
    "rw,nosuid,nodev,noexec,size=536870912,mode=1777"
)
# A same-profile unprivileged provisioner first mounts the fresh volume over
# the pinned image's empty mode-1777 /var/tmp.  Docker copy-up transfers only
# that reviewed directory metadata, after which the candidate can mount the
# persistent volume at the stable evidence API below without a root/chown
# helper.
EVIDENCE_PATH = "/evidence"
CORPUS_PATH = "/corpus"
_VOLUME_READY_MARKER = ".vibeic-volume-ready"
_STDOUT_ARTIFACT = "runner-stdout.bin"
_STDERR_ARTIFACT = "runner-stderr.bin"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PROGRESS_LINE = 1024 * 1024
MAX_IDENTITY_BYTES = 16 * 1024
MAX_PROGRESS_UNITS = 100_000
MAX_ARTEFACT_FILES = 100_000
MAX_ARTEFACT_BYTES = 512 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}\Z")
_RUN_NAME = re.compile(r"vibeic-candidate-[0-9a-f]{24}\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_FIXED_PROCESS_ENV = {
    "GATEKEEPER_RUNTIME_ROOT": RUNTIME_ROOT,
    # The object-exact subject is materialized by the trusted host parent and
    # mounted read-only for uid 65534.  Git therefore cannot infer ownership
    # from uid equality.  Bind the two reviewed repositories explicitly while
    # disabling ambient/user configuration and replacement-object authority.
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_KEY_0": "safe.directory",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_VALUE_0": WORKDIR,
    "GIT_CONFIG_KEY_1": "safe.directory",
    "GIT_CONFIG_VALUE_1": CORPUS_PATH,
    "GIT_NO_REPLACE_OBJECTS": "1",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "TMPDIR": "/tmp",
    "VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY": "1",
}
_LAND_PROCESS_ENV = {
    "GATEKEEPER_NO_STAMP": "1",
    "GATEKEEPER_SKIP_TARGETED_TESTS": "1",
    "VIBEIC_LANDING_COMPLETION": "/evidence/landing-completion.json",
    "VIBEIC_LANDING_PROGRESS": "/evidence/landing-progress.jsonl",
    "VIBE_IC_BENCHMARK_DATA": CORPUS_PATH,
}
_TEST_PROCESS_ENV = {
    "VIBE_IC_BENCHMARK_DATA": CORPUS_PATH,
    # Protected-runtime constant.  Keep it runner-owned so an ACTIVATE remains
    # bootable by the preceding BASE verifier, which cannot know new caller
    # arguments introduced by the candidate runtime.
    "VIBEIC_PYTEST_SEMANTIC_STALL_GRACE": "600",
}
_TEST_REVIEWED_ENV_NAMES = frozenset({
    "GATEKEEPER_BENCHMARK_DATA_SHA",
    "GATEKEEPER_VERIFY_ARM",
    "VIBEIC_PYTEST_PROGRESS_FILE",
    "VIBEIC_PYTEST_PROGRESS_NONCE",
})
_LAND_REVIEWED_ENV_NAMES = frozenset({
    "GATEKEEPER_BASE",
    "GATEKEEPER_BENCHMARK_DATA_SHA",
    "GATEKEEPER_HYGIENE_PROGRESS",
    "GATEKEEPER_HYGIENE_REPORT",
    "GATEKEEPER_VERIFY_ARM",
    "GATEKEEPER_VERSION_BY_GATEKEEPER",
    "VIBEIC_LANDING_PROGRESS_NONCE",
})
_REVIEWED_ENV_NAMES = _TEST_REVIEWED_ENV_NAMES | _LAND_REVIEWED_ENV_NAMES


class Refusal(RuntimeError):
    """The runner cannot produce trustworthy candidate evidence."""


class SignalExit(BaseException):
    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON number {token!r}")


def _no_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def strict_loads(raw: bytes | str, *, limit: int = MAX_JSON_BYTES) -> Any:
    if isinstance(raw, str):
        encoded = raw.encode("utf-8", "strict")
    else:
        encoded = raw
    if len(encoded) > limit:
        raise ValueError("JSON exceeds its resource bound")
    text = encoded.decode("utf-8", "strict")
    return json.loads(
        text,
        object_pairs_hook=_no_duplicates,
        parse_constant=_reject_constant,
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exact_keys(value: Any, keys: set[str], what: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{what} has the wrong schema")
    return value


def _exact_int(value: Any, what: str, minimum: int = 0,
               maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{what} is not an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{what} exceeds {maximum}")
    return value


def _bounded_string(value: Any, what: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ValueError(f"{what} is not an exact string")
    if "\0" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{what} contains a control separator")
    if len(value.encode("utf-8", "strict")) > MAX_IDENTITY_BYTES:
        raise ValueError(f"{what} exceeds its resource bound")
    return value


def _hex64(value: Any, what: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{what} is not a SHA-256 digest")
    return value


def _safe_rel(value: Any, what: str) -> str:
    text = _bounded_string(value, what)
    rel = PurePosixPath(text)
    if rel.is_absolute() or ".." in rel.parts or str(rel) != text:
        raise ValueError(f"{what} is not a canonical relative path")
    return text


def _overlay_paths(values: Sequence[str], runtime: Path,
                   subject: Path) -> list[dict[str, Any]]:
    if not values or list(values) != sorted(set(values)):
        raise Refusal("--overlay paths must be a non-empty sorted unique manifest")
    rows: list[dict[str, Any]] = []
    for raw in values:
        try:
            rel = _safe_rel(raw, "runtime overlay path")
        except ValueError as exc:
            raise Refusal(str(exc)) from exc
        source = runtime.joinpath(*PurePosixPath(rel).parts)
        target = subject.joinpath(*PurePosixPath(rel).parts)
        try:
            source_info = source.lstat()
            target_info = target.lstat()
        except OSError as exc:
            raise Refusal(f"runtime overlay {rel!r} is missing: {exc}") from exc
        if (not stat.S_ISREG(source_info.st_mode)
                or not stat.S_ISREG(target_info.st_mode)):
            raise Refusal(f"runtime overlay {rel!r} is not regular in both trees")
        rows.append({
            "destination": f"{WORKDIR}/{rel}",
            "path": rel,
            "source": str(source),
            "source_file": _file_digest(source),
        })
    return rows


def _reviewed_process_env(values: Sequence[str]) -> dict[str, str]:
    if list(values) != sorted(set(values)):
        raise Refusal("--env entries must be sorted and unique")
    out: dict[str, str] = {}
    for raw in values:
        if (not isinstance(raw, str) or "=" not in raw or "\0" in raw
                or "\r" in raw or "\n" in raw
                or len(raw.encode("utf-8", "strict")) > MAX_IDENTITY_BYTES):
            raise Refusal("--env entry is not a bounded NAME=VALUE string")
        name, value = raw.split("=", 1)
        if _ENV_NAME.fullmatch(name) is None or name not in _REVIEWED_ENV_NAMES:
            raise Refusal(f"--env name {name!r} is not in the reviewed allowlist")
        if name in out or name in _FIXED_PROCESS_ENV:
            raise Refusal(f"--env name {name!r} is repeated/fixed")
        if name in {"GATEKEEPER_BASE", "GATEKEEPER_BENCHMARK_DATA_SHA"}:
            if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
                raise Refusal(f"{name} must be a full lowercase object digest")
        elif name in {"VIBEIC_LANDING_PROGRESS_NONCE",
                      "VIBEIC_PYTEST_PROGRESS_NONCE"}:
            if _HEX64.fullmatch(value) is None:
                raise Refusal(f"{name} must be 64 lowercase hex digits")
        elif name in {"GATEKEEPER_HYGIENE_PROGRESS",
                      "GATEKEEPER_HYGIENE_REPORT",
                      "VIBEIC_PYTEST_PROGRESS_FILE"}:
            path = PurePosixPath(value)
            if (not path.is_absolute() or ".." in path.parts
                    or str(path) != value or value == EVIDENCE_PATH
                    or not value.startswith(EVIDENCE_PATH + "/")):
                raise Refusal(f"{name} must be a canonical path under evidence")
            relative = path.relative_to(EVIDENCE_PATH)
            if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", part) is None
                   for part in relative.parts):
                raise Refusal(f"{name} contains an unsafe evidence path component")
        elif name == "GATEKEEPER_VERIFY_ARM":
            if value not in {"A1", "A2", "B1", "B2"}:
                raise Refusal("GATEKEEPER_VERIFY_ARM must be A1, A2, B1, or B2")
        elif name == "GATEKEEPER_VERSION_BY_GATEKEEPER":
            if value not in {"0", "1"}:
                raise Refusal("GATEKEEPER_VERSION_BY_GATEKEEPER must be 0 or 1")
        out[name] = value
    arm = out.get("GATEKEEPER_VERIFY_ARM")
    if arm is None:
        raise Refusal("required reviewed --env GATEKEEPER_VERIFY_ARM is missing")
    expected = (_TEST_REVIEWED_ENV_NAMES if arm in {"A1", "B1"}
                else _LAND_REVIEWED_ENV_NAMES)
    missing = sorted(expected - set(out))
    excess = sorted(set(out) - expected)
    if missing or excess:
        raise Refusal(
            f"reviewed --env set differs for arm {arm}; "
            f"missing={missing!r}, excess={excess!r}")
    return out


def _fixed_process_env(arm: str) -> dict[str, str]:
    out = dict(_FIXED_PROCESS_ENV)
    if arm in {"A2", "B2"}:
        out.update(_LAND_PROCESS_ENV)
    else:
        out.update(_TEST_PROCESS_ENV)
    return out


def _receipt_process_env(values: Any) -> dict[str, str]:
    if (not isinstance(values, list) or not values
            or not all(isinstance(item, str) for item in values)
            or values != sorted(set(values))):
        raise ValueError("receipt process environment is not sorted/unique")
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("receipt process environment entry lacks '='")
        name, value = item.split("=", 1)
        if _ENV_NAME.fullmatch(name) is None or name in parsed:
            raise ValueError("receipt process environment name differs")
        parsed[name] = value
    dynamic = {
        "VIBEIC_HERMETIC_EVIDENCE_PATH",
        "VIBEIC_HERMETIC_PROGRESS_NONCE",
        "VIBEIC_HERMETIC_PROGRESS_PATH",
        "VIBEIC_HERMETIC_PROGRESS_PREFIX",
        "VIBEIC_HERMETIC_PROGRESS_SCOPE",
    }
    reviewed_present = set(parsed) & set(_REVIEWED_ENV_NAMES)
    try:
        reviewed = _reviewed_process_env(
            [f"{name}={parsed[name]}" for name in sorted(reviewed_present)])
    except Refusal as exc:
        raise ValueError(f"receipt reviewed environment differs: {exc}") from exc
    fixed = _fixed_process_env(reviewed["GATEKEEPER_VERIFY_ARM"])
    expected = set(fixed) | set(reviewed) | dynamic
    if set(parsed) != expected:
        raise ValueError("receipt process environment name set differs")
    for name, value in fixed.items():
        if parsed[name] != value:
            raise ValueError(f"receipt fixed environment differs for {name}")
    if (parsed["VIBEIC_HERMETIC_EVIDENCE_PATH"] != EVIDENCE_PATH
            or parsed["VIBEIC_HERMETIC_PROGRESS_PATH"]
            != "/input/progress-plan.json"
            or parsed["VIBEIC_HERMETIC_PROGRESS_PREFIX"]
            != PROGRESS_PREFIX.decode("ascii")
            or _HEX64.fullmatch(parsed["VIBEIC_HERMETIC_PROGRESS_NONCE"]) is None):
        raise ValueError("receipt hermetic protocol environment differs")
    _bounded_string(parsed["VIBEIC_HERMETIC_PROGRESS_SCOPE"],
                    "receipt hermetic progress scope")
    return parsed


def _load_one_json_output(proc: subprocess.CompletedProcess[bytes], what: str
                          ) -> dict[str, Any]:
    if proc.returncode != 0:
        error = proc.stderr.decode("utf-8", "replace").strip()
        raise Refusal(f"{what} failed: {error[:500]}")
    try:
        doc = strict_loads(proc.stdout)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise Refusal(f"{what} returned ambiguous JSON: {exc}") from exc
    if not isinstance(doc, list) or len(doc) != 1 or not isinstance(doc[0], dict):
        raise Refusal(f"{what} did not return exactly one object")
    return doc[0]


class Docker:
    def __init__(self, executable: str):
        self.executable = executable
        self.env = dict(os.environ)
        self.env["LC_ALL"] = "C"

    def call(self, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [self.executable, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                check=False,
            )
        except OSError as exc:
            raise Refusal(f"cannot execute Docker CLI: {exc}") from exc

    def checked(self, args: Sequence[str], what: str) -> bytes:
        proc = self.call(args)
        if proc.returncode != 0:
            error = proc.stderr.decode("utf-8", "replace").strip()
            raise Refusal(f"{what} failed: {error[:500]}")
        return proc.stdout

    def popen(self, args: Sequence[str]) -> subprocess.Popen[bytes]:
        try:
            return subprocess.Popen(
                [self.executable, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                start_new_session=True,
            )
        except OSError as exc:
            raise Refusal(f"cannot start Docker CLI: {exc}") from exc


def _home_path() -> Path:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise Refusal(f"cannot resolve the host account home: {exc}") from exc


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_mount(path: Path, kind: str, home: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        info = resolved.lstat()
    except OSError as exc:
        raise Refusal(f"cannot resolve {kind}: {exc}") from exc
    if _inside(resolved, home):
        raise Refusal(f"{kind} would expose the host HOME to the candidate")
    if kind in {"subject", "runtime", "corpus"}:
        if not stat.S_ISDIR(info.st_mode):
            raise Refusal(f"{kind} is not a directory")
    elif not stat.S_ISREG(info.st_mode):
        raise Refusal(f"{kind} is not a regular file")
    return resolved


def _read_regular(path: Path) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise Refusal(f"non-regular file in candidate input: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(fd)
    finally:
        os.close(fd)
    after = path.lstat()
    identity_before = (
        before.st_dev, before.st_ino, before.st_mode, before.st_size,
        before.st_mtime_ns, before.st_ctime_ns,
    )
    identity_fd = (
        after_fd.st_dev, after_fd.st_ino, after_fd.st_mode, after_fd.st_size,
        after_fd.st_mtime_ns, after_fd.st_ctime_ns,
    )
    identity_after = (
        after.st_dev, after.st_ino, after.st_mode, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns,
    )
    if identity_before != identity_fd or identity_before != identity_after:
        raise Refusal(f"candidate input changed while hashed: {path}")
    return b"".join(chunks), before


def _tree_digest(root: Path, role: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    root_info = root.lstat()
    if stat.S_IMODE(root_info.st_mode) & 0o005 != 0o005:
        raise Refusal(f"{role} root is not readable/traversable by uid 65534")
    directories: list[dict[str, str]] = []
    total = 0
    def walk_error(exc: OSError) -> None:
        raise Refusal(f"cannot enumerate {role}: {exc}")

    for current, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=walk_error):
        base = Path(current)
        dirnames.sort()
        filenames.sort()
        for name in list(dirnames):
            child = base / name
            info = child.lstat()
            rel = child.relative_to(root).as_posix()
            rel.encode("utf-8", "strict")
            if not stat.S_ISDIR(info.st_mode):
                raise Refusal(f"{role} contains a symlink/special path: {rel}")
            permissions = stat.S_IMODE(info.st_mode)
            if permissions & 0o005 != 0o005:
                raise Refusal(
                    f"{role} directory is not readable/traversable by uid 65534: {rel}")
            directories.append({"path": rel, "permissions": f"{permissions:04o}"})
        for name in filenames:
            child = base / name
            rel = child.relative_to(root).as_posix()
            _safe_rel(rel, f"{role} path")
            data, info = _read_regular(child)
            permissions = stat.S_IMODE(info.st_mode)
            if not permissions & stat.S_IROTH:
                raise Refusal(f"{role} file is not readable by uid 65534: {rel}")
            mode = "100755" if info.st_mode & 0o111 else "100644"
            entries.append({
                "mode": mode,
                "path": rel,
                "permissions": f"{permissions:04o}",
                "sha256": _sha256(data),
                "size": len(data),
            })
            total += len(data)
    doc = {
        "directories": sorted(directories, key=lambda row: row["path"]),
        "files": entries,
        "root_permissions": f"{stat.S_IMODE(root_info.st_mode):04o}",
        "schema": SCHEMA,
    }
    return {
        "digest": _sha256(_canonical(doc)),
        "directories": len(directories),
        "files": len(entries),
        "total_bytes": total,
    }


def _file_digest(path: Path) -> dict[str, Any]:
    data, info = _read_regular(path)
    permissions = stat.S_IMODE(info.st_mode)
    if not permissions & stat.S_IROTH:
        raise Refusal(f"candidate input file is not readable by uid 65534: {path}")
    return {
        "mode": "100755" if info.st_mode & 0o111 else "100644",
        "permissions": f"{permissions:04o}",
        "sha256": _sha256(data),
        "size": len(data),
    }


def _load_progress_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw = path.read_bytes()
        doc = strict_loads(raw, limit=1024 * 1024)
        _exact_keys(doc, {"schema", "scope", "stall_grace_seconds", "units"},
                    "progress plan")
        if doc["schema"] != SCHEMA or type(doc["schema"]) is not int:
            raise ValueError("progress plan schema is unknown")
        scope = _bounded_string(doc["scope"], "progress scope")
        grace = _exact_int(doc["stall_grace_seconds"], "stall grace", 1, 86400)
        units = doc["units"]
        if (not isinstance(units, list) or not units
                or len(units) > MAX_PROGRESS_UNITS):
            raise ValueError("progress plan units are not a bounded non-empty list")
        exact_units = [_bounded_string(item, "progress unit") for item in units]
        if len(exact_units) != len(set(exact_units)):
            raise ValueError("progress plan repeats a unit")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise Refusal(f"invalid finite semantic progress plan: {exc}") from exc
    summary = {
        "sha256": _sha256(raw),
        "size": len(raw),
    }
    return {
        "schema": SCHEMA,
        "scope": scope,
        "stall_grace_seconds": grace,
        "units": exact_units,
    }, summary


class Progress:
    def __init__(self, nonce: str, scope: str, units: Sequence[str]):
        self.nonce = nonce
        self.scope = scope
        self.units = tuple(units)
        self.next_record = 0
        self.completed = 0
        self.raw_records: list[bytes] = []

    def _expected(self) -> dict[str, Any]:
        common = {
            "nonce": self.nonce,
            "schema": SCHEMA,
            "scope": self.scope,
            "seq": self.next_record,
            "total": len(self.units),
        }
        if self.next_record == 0:
            return {**common, "state": "start"}
        if 1 <= self.next_record <= len(self.units):
            return {
                **common,
                "completed": self.next_record,
                "state": "checkpoint",
                "unit": self.units[self.next_record - 1],
            }
        if self.next_record == len(self.units) + 1:
            return {
                **common,
                "completed": len(self.units),
                "state": "terminal",
            }
        raise Refusal("semantic progress has excess records")

    def accept(self, line: bytes) -> bool:
        payload = line[len(PROGRESS_PREFIX):]
        if len(payload) > MAX_PROGRESS_LINE:
            raise Refusal("semantic progress record exceeds its resource bound")
        try:
            row = strict_loads(payload, limit=MAX_PROGRESS_LINE)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise Refusal(f"malformed semantic progress record: {exc}") from exc
        expected = self._expected()
        if row != expected or type(row.get("schema")) is not int:
            raise Refusal("semantic progress differs from the parent-owned FSM")
        if payload != _canonical(expected):
            raise Refusal("semantic progress record is not canonical JSON")
        meaningful = expected["state"] == "checkpoint"
        if meaningful:
            self.completed += 1
        self.raw_records.append(payload)
        self.next_record += 1
        return meaningful

    def finish(self) -> dict[str, Any]:
        if self.next_record != len(self.units) + 2:
            raise Refusal("candidate ended without the exact semantic terminal record")
        wire = b"\n".join(self.raw_records) + b"\n"
        return {
            "completed": self.completed,
            "protocol_sha256": _sha256(wire),
            "records": len(self.raw_records),
            "scope": self.scope,
            "total": len(self.units),
            "units": list(self.units),
        }


class ProgressLines:
    def __init__(self, progress: Progress):
        self.progress = progress
        self.buffer = b""

    def feed(self, chunk: bytes) -> bool:
        meaningful = False
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if line.startswith(PROGRESS_PREFIX):
                meaningful = self.progress.accept(line) or meaningful
        if len(self.buffer) > MAX_PROGRESS_LINE + len(PROGRESS_PREFIX):
            if self.buffer.startswith(PROGRESS_PREFIX):
                raise Refusal("unterminated semantic progress record is oversized")
            # Ordinary candidate output is evidence, not liveness.  It need not
            # be line-oriented and cannot renew the semantic lease.
            self.buffer = self.buffer[-len(PROGRESS_PREFIX):]
        return meaningful

    def finish(self) -> None:
        if self.buffer.startswith(PROGRESS_PREFIX):
            raise Refusal("semantic progress ended in a truncated record")


@dataclass
class Resources:
    docker: Docker
    container: str | None = None
    exporter: str | None = None
    provisioner: str | None = None
    volume: str | None = None
    attach: subprocess.Popen[bytes] | None = None

    def cleanup_owned(self) -> None:
        """Retain ownership through forced removal and absence inspection."""
        for owned in (self.exporter, self.container, self.provisioner):
            if owned is not None:
                self.docker.call(["container", "kill", owned])
        if self.attach is not None and self.attach.poll() is None:
            try:
                os.killpg(self.attach.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            self.attach.wait()
        for attribute in ("exporter", "container", "provisioner"):
            owned = getattr(self, attribute)
            if owned is not None:
                self.docker.call(["container", "rm", "--force", owned])
                try:
                    _prove_absent(self.docker, "container", owned)
                except Refusal:
                    # The outer result is already NORECORD.  Retain the name in
                    # the exception text and make the failed ownership proof
                    # observable instead of ever claiming cleanup evidence.
                    print(f"[NORECORD] cleanup could not prove {owned!r} absent",
                          file=sys.stderr)
                setattr(self, attribute, None)
        if self.volume is not None:
            self.docker.call(["volume", "rm", "--force", self.volume])
            try:
                _prove_absent(self.docker, "volume", self.volume)
            except Refusal:
                print(f"[NORECORD] cleanup could not prove volume "
                      f"{self.volume!r} absent", file=sys.stderr)
            self.volume = None


def _image_profile(docker: Docker) -> dict[str, Any]:
    proc = docker.call(["image", "inspect", IMAGE])
    doc = _load_one_json_output(proc, "fixed image inspection")
    image_id = doc.get("Id")
    if (not isinstance(image_id, str) or not image_id.startswith("sha256:")
            or _HEX64.fullmatch(image_id[7:]) is None):
        raise Refusal("fixed image has no exact content ID")
    repo_digests = doc.get("RepoDigests")
    if (not isinstance(repo_digests, list)
            or IMAGE_REPO_DIGEST not in repo_digests
            or not all(isinstance(item, str) for item in repo_digests)):
        raise Refusal("fixed image inspection does not bind the requested digest")
    if doc.get("Os") != "linux" or doc.get("Architecture") != "amd64":
        raise Refusal("fixed image platform differs from linux/amd64")
    return {
        "id": image_id,
        "platform": PLATFORM,
        "reference": IMAGE,
        "repo_digest": IMAGE_REPO_DIGEST,
    }


def _volume_create(docker: Docker, name: str, owner_label: str) -> dict[str, Any]:
    raw = docker.checked([
        "volume", "create",
        "--driver", "local",
        "--label", f"ai.vibeic.hermetic-run={owner_label}",
        name,
    ], "private evidence volume creation")
    if raw.decode("utf-8", "strict").strip() != name:
        raise Refusal("Docker created an unexpected evidence volume")
    proc = docker.call(["volume", "inspect", name])
    doc = _load_one_json_output(proc, "private evidence volume inspection")
    if (doc.get("Name") != name or doc.get("Driver") != "local"
            or doc.get("Scope") != "local"):
        raise Refusal("evidence volume identity/profile differs")
    options = doc.get("Options")
    expected_options: dict[str, str] = {}
    if options not in (None, expected_options):
        raise Refusal("evidence volume has unowned driver options")
    labels = doc.get("Labels")
    if (not isinstance(labels, dict)
            or labels.get("ai.vibeic.hermetic-run") != owner_label):
        raise Refusal("evidence volume ownership label differs")
    return {"driver": "local", "name": name, "options": expected_options}


def _mount_arg(source: Path | str, destination: str, *, readonly: bool,
               volume: bool = False) -> str:
    if volume:
        suffix = ",readonly" if readonly else ""
        return f"type=volume,src={source},dst={destination}{suffix}"
    suffix = ",bind-propagation=rprivate"
    if readonly:
        suffix += ",readonly"
    return f"type=bind,src={source},dst={destination}{suffix}"


def _inspect_container(docker: Docker, name: str, what: str) -> dict[str, Any]:
    proc = docker.call(["container", "inspect", name])
    return _load_one_json_output(proc, what)


def _validate_container_profile(
    doc: dict[str, Any], *, name: str, image: dict[str, Any], command: list[str],
    mounts: dict[str, Path], overlays: list[dict[str, Any]], volume: str,
    process_environment: list[str],
) -> dict[str, Any]:
    cid = doc.get("Id")
    if not isinstance(cid, str) or _CONTAINER_ID.fullmatch(cid) is None:
        raise Refusal("candidate container ID is malformed")
    if doc.get("Name") not in {name, "/" + name}:
        raise Refusal("candidate container name differs")
    if doc.get("Image") != image["id"]:
        raise Refusal("candidate container resolved a different image ID")
    config = doc.get("Config")
    host = doc.get("HostConfig")
    observed_mounts = doc.get("Mounts")
    if not isinstance(config, dict) or not isinstance(host, dict):
        raise Refusal("candidate container inspection lacks configuration")
    if (config.get("User") != USER or config.get("WorkingDir") != WORKDIR
            or config.get("Image") != IMAGE
            or config.get("Entrypoint") != ["/usr/bin/env"]
            or config.get("Cmd") != [
                "-i", "--", *process_environment, *command
            ]):
        raise Refusal("candidate command/user/workdir/image configuration differs")
    if (config.get("AttachStdin") is not False
            or config.get("OpenStdin") is not False
            or config.get("Tty") is not False):
        raise Refusal("candidate container unexpectedly owns an interactive input")
    env = config.get("Env")
    if not isinstance(env, list) or not all(isinstance(item, str) for item in env):
        raise Refusal("candidate environment is malformed")
    restart = host.get("RestartPolicy")
    if (not isinstance(restart, dict) or restart.get("Name") not in {"", "no"}
            or restart.get("MaximumRetryCount") != 0):
        raise Refusal("candidate restart policy is not disabled")
    if (host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("AutoRemove") is not False
            or host.get("PublishAllPorts") is not False):
        raise Refusal("candidate least-privilege host profile differs")
    if host.get("CapDrop") != ["ALL"] or host.get("CapAdd") not in (None, []):
        raise Refusal("candidate Linux capability profile differs")
    security = host.get("SecurityOpt")
    if (not isinstance(security, list) or len(security) != 1
            or security[0] not in {
                "no-new-privileges:true", "no-new-privileges=true"
            }):
        raise Refusal("candidate no-new-privileges profile differs")
    if host.get("Tmpfs") != {"/tmp": TMPFS_OPTIONS}:
        raise Refusal("candidate /tmp tmpfs profile differs")
    if host.get("Binds") not in (None, []):
        raise Refusal("candidate has an unowned legacy bind mount")
    if host.get("Devices") not in (None, []):
        raise Refusal("candidate has a host device")

    if not isinstance(observed_mounts, list):
        raise Refusal("candidate mount inspection is malformed")
    expected_destinations = {
        WORKDIR: ("subject", str(mounts["subject"])),
        RUNTIME_ROOT: ("runtime", str(mounts["runtime"])),
        CORPUS_PATH: ("corpus", str(mounts["corpus"])),
        "/input/selection": ("selection", str(mounts["selection"])),
        "/input/progress-plan.json": ("progress_plan", str(mounts["progress_plan"])),
    }
    for overlay in overlays:
        expected_destinations[overlay["destination"]] = (
            f"runtime_overlay:{overlay['path']}", overlay["source"])
    projection: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in observed_mounts:
        if not isinstance(item, dict) or not isinstance(item.get("Destination"), str):
            raise Refusal("candidate mount record is malformed")
        destination = item["Destination"]
        if destination in seen:
            raise Refusal("candidate repeats a mount destination")
        seen.add(destination)
        if destination in expected_destinations:
            role, source = expected_destinations[destination]
            if (item.get("Type") != "bind" or item.get("Source") != source
                    or item.get("RW") is not False
                    or item.get("Propagation") not in {"rprivate", ""}):
                raise Refusal(f"candidate {role} bind is not exact/read-only")
            projection.append({
                "destination": destination,
                "read_only": True,
                "role": role,
                "source": source,
                "type": "bind",
            })
        elif destination == EVIDENCE_PATH:
            if (item.get("Type") != "volume" or item.get("Name") != volume
                    or item.get("RW") is not True):
                raise Refusal("candidate evidence volume mount differs")
            projection.append({
                "destination": destination,
                "read_only": False,
                "role": "evidence",
                "source": volume,
                "type": "volume",
            })
        elif destination == "/tmp":
            if item.get("Type") != "tmpfs" or item.get("RW") is not True:
                raise Refusal("candidate /tmp mount differs")
        else:
            raise Refusal(f"candidate has an unowned mount at {destination}")
    if seen - {"/tmp"} != set(expected_destinations) | {EVIDENCE_PATH}:
        raise Refusal("candidate mount set is incomplete")
    if any("docker.sock" in str(item) for item in observed_mounts):
        raise Refusal("candidate inspection exposes docker.sock")
    return {
        "cap_drop": ["ALL"],
        "command": command,
        "container_id": cid,
        "environment_sha256": _sha256(_canonical(env)),
        "launcher": ["/usr/bin/env", "-i", "--"],
        "mounts": sorted(projection, key=lambda row: row["destination"]),
        "network": "none",
        "no_new_privileges": True,
        "process_environment": process_environment,
        "read_only_rootfs": True,
        "restart": "no",
        "tmpfs": {"destination": "/tmp", "options": TMPFS_OPTIONS},
        "user": USER,
        "workdir": WORKDIR,
    }


def _validate_exporter_profile(
    doc: dict[str, Any], *, name: str, image: dict[str, Any], volume: str,
    destination: Path,
) -> dict[str, Any]:
    """Bind the trusted, post-stop volume-to-host evidence transport."""
    cid = doc.get("Id")
    config = doc.get("Config")
    host = doc.get("HostConfig")
    mounts = doc.get("Mounts")
    copy_command = [
        "/bin/cp", "-R", "--no-preserve=mode,ownership",
        "/evidence/.", "/export/",
    ]
    if (not isinstance(cid, str) or _CONTAINER_ID.fullmatch(cid) is None
            or doc.get("Name") not in {name, "/" + name}
            or doc.get("Image") != image["id"]
            or not isinstance(config, dict) or not isinstance(host, dict)
            or config.get("Image") != IMAGE or config.get("User") != USER
            or config.get("WorkingDir") != "/"
            or config.get("Entrypoint") != [copy_command[0]]
            or config.get("Cmd") != copy_command[1:]
            or config.get("AttachStdin") is not False
            or config.get("OpenStdin") is not False
            or config.get("Tty") is not False):
        raise Refusal("post-stop evidence exporter identity/configuration differs")
    restart = host.get("RestartPolicy")
    if (host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("AutoRemove") is not False
            or host.get("PublishAllPorts") is not False
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd") not in (None, [])
            or host.get("Devices") not in (None, [])
            or host.get("Binds") not in (None, [])
            or not isinstance(restart, dict)
            or restart.get("Name") not in {"", "no"}
            or restart.get("MaximumRetryCount") != 0
            or host.get("Tmpfs") != {"/tmp": TMPFS_OPTIONS}):
        raise Refusal("post-stop evidence exporter least-privilege profile differs")
    security = host.get("SecurityOpt")
    if (not isinstance(security, list) or len(security) != 1
            or security[0] not in {
                "no-new-privileges:true", "no-new-privileges=true"
            }):
        raise Refusal("post-stop evidence exporter security profile differs")
    if not isinstance(mounts, list):
        raise Refusal("post-stop evidence exporter mount inspection is malformed")
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in mounts:
        if not isinstance(item, dict) or not isinstance(item.get("Destination"), str):
            raise Refusal("post-stop evidence exporter mount record is malformed")
        mount_destination = item["Destination"]
        if mount_destination in seen:
            raise Refusal("post-stop evidence exporter repeats a mount")
        seen.add(mount_destination)
        if mount_destination == "/evidence":
            if (item.get("Type") != "volume" or item.get("Name") != volume
                    or item.get("RW") is not False):
                raise Refusal("post-stop evidence exporter volume is not read-only")
            projected.append({
                "destination": "/evidence", "read_only": True,
                "role": "evidence", "source": volume, "type": "volume",
            })
        elif mount_destination == "/export":
            if (item.get("Type") != "bind"
                    or item.get("Source") != str(destination)
                    or item.get("RW") is not True
                    or item.get("Propagation") not in {"rprivate", ""}):
                raise Refusal("post-stop evidence destination bind differs")
            projected.append({
                "destination": "/export", "read_only": False,
                "role": "post_stop_export", "source": str(destination),
                "type": "bind",
            })
        elif mount_destination == "/tmp":
            if item.get("Type") != "tmpfs" or item.get("RW") is not True:
                raise Refusal("post-stop evidence exporter /tmp differs")
        else:
            raise Refusal("post-stop evidence exporter has an unowned mount")
    if seen - {"/tmp"} != {"/evidence", "/export"}:
        raise Refusal("post-stop evidence exporter mount set is incomplete")
    env = config.get("Env")
    if not isinstance(env, list) or not all(isinstance(item, str) for item in env):
        raise Refusal("post-stop evidence exporter environment is malformed")
    return {
        "cap_drop": ["ALL"],
        "command": copy_command,
        "container_id": cid,
        "environment_sha256": _sha256(_canonical(env)),
        "mounts": sorted(projected, key=lambda row: row["destination"]),
        "network": "none",
        "no_new_privileges": True,
        "read_only_rootfs": True,
        "restart": "no",
        "tmpfs": {"destination": "/tmp", "options": TMPFS_OPTIONS},
        "user": USER,
        "workdir": "/",
    }


def _validate_provisioner_profile(
    doc: dict[str, Any], *, name: str, image: dict[str, Any], volume: str,
) -> dict[str, Any]:
    """Bind the uid-65534, capability-free standard-volume copy-up step."""
    cid = doc.get("Id")
    config = doc.get("Config")
    host = doc.get("HostConfig")
    mounts = doc.get("Mounts")
    if (not isinstance(cid, str) or _CONTAINER_ID.fullmatch(cid) is None
            or doc.get("Name") not in {name, "/" + name}
            or doc.get("Image") != image["id"]
            or not isinstance(config, dict) or not isinstance(host, dict)
            or config.get("Image") != IMAGE or config.get("User") != USER
            or config.get("WorkingDir") != "/"
            or config.get("Entrypoint") != ["/usr/bin/env"]
            or config.get("Cmd") != [
                "-i", "--", "/usr/bin/touch",
                f"/var/tmp/{_VOLUME_READY_MARKER}",
            ]
            or config.get("AttachStdin") is not False
            or config.get("OpenStdin") is not False
            or config.get("Tty") is not False):
        raise Refusal("evidence volume provisioner identity/configuration differs")
    restart = host.get("RestartPolicy")
    security = host.get("SecurityOpt")
    if (host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("AutoRemove") is not False
            or host.get("PublishAllPorts") is not False
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd") not in (None, [])
            or host.get("Devices") not in (None, [])
            or host.get("Binds") not in (None, [])
            or not isinstance(restart, dict)
            or restart.get("Name") not in {"", "no"}
            or restart.get("MaximumRetryCount") != 0
            or host.get("Tmpfs") != {"/tmp": TMPFS_OPTIONS}
            or not isinstance(security, list) or len(security) != 1
            or security[0] not in {
                "no-new-privileges:true", "no-new-privileges=true"
            }):
        raise Refusal("evidence volume provisioner least-privilege profile differs")
    if not isinstance(mounts, list):
        raise Refusal("evidence volume provisioner mount inspection is malformed")
    relevant = [item for item in mounts
                if isinstance(item, dict) and item.get("Destination") != "/tmp"]
    if (len(relevant) != 1 or relevant[0].get("Destination") != "/var/tmp"
            or relevant[0].get("Type") != "volume"
            or relevant[0].get("Name") != volume
            or relevant[0].get("RW") is not True):
        raise Refusal("evidence volume provisioner mount differs")
    env = config.get("Env")
    if not isinstance(env, list) or not all(isinstance(item, str) for item in env):
        raise Refusal("evidence volume provisioner environment is malformed")
    return {
        "cap_drop": ["ALL"],
        "command": ["/usr/bin/touch", f"/var/tmp/{_VOLUME_READY_MARKER}"],
        "container_id": cid,
        "environment_sha256": _sha256(_canonical(env)),
        "launcher": ["/usr/bin/env", "-i", "--"],
        "mount": {
            "destination": "/var/tmp", "read_only": False,
            "role": "volume_metadata_copyup", "source": volume,
            "type": "volume",
        },
        "network": "none",
        "no_new_privileges": True,
        "read_only_rootfs": True,
        "restart": "no",
        "tmpfs": {"destination": "/tmp", "options": TMPFS_OPTIONS},
        "user": USER,
        "workdir": "/",
    }


def _provision_volume(
    docker: Docker, resources: Resources, *, run_id: str,
    image: dict[str, Any], volume: str,
) -> dict[str, Any]:
    name = f"vibeic-candidate-provision-{run_id}"
    create_args = [
        "container", "create", "--pull=never", "--platform", PLATFORM,
        "--name", name,
        "--label", f"ai.vibeic.hermetic-provision={run_id}",
        "--user", USER,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--restart", "no",
        "--tmpfs", f"/tmp:{TMPFS_OPTIONS}",
        "--workdir", "/",
        "--entrypoint", "/usr/bin/env",
        "--mount", _mount_arg(volume, "/var/tmp", readonly=False, volume=True),
        IMAGE,
        "-i", "--", "/usr/bin/touch", f"/var/tmp/{_VOLUME_READY_MARKER}",
    ]
    raw_cid = docker.checked(create_args, "evidence volume provisioner creation")
    cid = raw_cid.decode("ascii", "strict").strip()
    if _CONTAINER_ID.fullmatch(cid) is None:
        raise Refusal("Docker returned a malformed volume provisioner ID")
    resources.provisioner = name
    created = _inspect_container(docker, name, "created volume provisioner inspection")
    profile = _validate_provisioner_profile(
        created, name=name, image=image, volume=volume)
    if profile["container_id"] != cid:
        raise Refusal("created volume provisioner ID differs from inspection")
    proc = docker.popen(["container", "start", "--attach", name])
    resources.attach = proc
    stdout, stderr = proc.communicate()
    attach_rc = proc.returncode
    resources.attach = None
    stopped = _inspect_container(docker, name, "stopped volume provisioner inspection")
    if stopped.get("Id") != cid or stopped.get("Image") != image["id"]:
        raise Refusal("stopped volume provisioner identity changed")
    state = _stopped_state(stopped)
    if attach_rc != 0 or state["exit_code"] != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise Refusal(f"evidence volume provisioning failed: {detail[:500]}")
    docker.checked(["container", "rm", name], "volume provisioner removal")
    _prove_absent(docker, "container", name)
    resources.provisioner = None
    profile["result"] = {**state, "attach_exit_code": attach_rc}
    profile["streams"] = {
        "stderr": {"sha256": _sha256(stderr), "size": len(stderr)},
        "stdout": {"sha256": _sha256(stdout), "size": len(stdout)},
    }
    profile["removed"] = True
    return profile


def _post_stop_export(
    docker: Docker, resources: Resources, *, run_id: str,
    image: dict[str, Any], volume: str, destination: Path,
) -> dict[str, Any]:
    name = f"vibeic-candidate-export-{run_id}"
    copy_command = [
        "/bin/cp", "-R", "--no-preserve=mode,ownership",
        "/evidence/.", "/export/",
    ]
    create_args = [
        "container", "create", "--pull=never",
        "--platform", PLATFORM,
        "--name", name,
        "--label", f"ai.vibeic.hermetic-export={run_id}",
        "--user", USER,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--restart", "no",
        "--tmpfs", f"/tmp:{TMPFS_OPTIONS}",
        "--workdir", "/",
        "--entrypoint", copy_command[0],
        "--mount", _mount_arg(volume, "/evidence", readonly=True, volume=True),
        "--mount", _mount_arg(destination, "/export", readonly=False),
        IMAGE,
        *copy_command[1:],
    ]
    raw_cid = docker.checked(create_args, "post-stop evidence exporter creation")
    cid = raw_cid.decode("ascii", "strict").strip()
    if _CONTAINER_ID.fullmatch(cid) is None:
        raise Refusal("Docker returned a malformed evidence exporter ID")
    resources.exporter = name
    created = _inspect_container(docker, name, "created evidence exporter inspection")
    profile = _validate_exporter_profile(
        created, name=name, image=image, volume=volume, destination=destination,
    )
    if profile["container_id"] != cid:
        raise Refusal("created evidence exporter ID differs from inspection")
    proc = docker.popen(["container", "start", "--attach", name])
    resources.attach = proc
    stdout, stderr = proc.communicate()
    attach_rc = proc.returncode
    resources.attach = None
    stopped = _inspect_container(docker, name, "stopped evidence exporter inspection")
    if stopped.get("Id") != cid or stopped.get("Image") != image["id"]:
        raise Refusal("stopped evidence exporter identity changed")
    state = _stopped_state(stopped)
    if attach_rc != 0 or state["exit_code"] != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise Refusal(f"post-stop evidence export failed: {detail[:500]}")
    profile["result"] = {**state, "attach_exit_code": attach_rc}
    profile["streams"] = {
        "stderr": {"sha256": _sha256(stderr), "size": len(stderr)},
        "stdout": {"sha256": _sha256(stdout), "size": len(stdout)},
    }
    return profile


def _run_monitored(
    docker: Docker, resources: Resources, name: str, progress: Progress,
    grace: int, stdout_path: Path, stderr_path: Path,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    proc = docker.popen(["container", "start", "--attach", name])
    resources.attach = proc
    assert proc.stdout is not None and proc.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    parser = ProgressLines(progress)
    deadline = time.monotonic() + grace
    streams: dict[str, tuple[BinaryIO, hashlib._Hash, int]] = {}
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        streams["stdout"] = (stdout_file, hashlib.sha256(), 0)
        streams["stderr"] = (stderr_file, hashlib.sha256(), 0)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                completed = progress.completed
                total = len(progress.units)
                last = progress.units[completed - 1] if completed else "<none>"
                next_unit = progress.units[completed] if completed < total else "<terminal>"
                raise Refusal(
                    "candidate semantic progress stalled; no elapsed-runtime "
                    "verdict was inferred; "
                    f"completed={completed}/{total}; last={last}; next={next_unit}"
                )
            events = selector.select(min(remaining, 0.25))
            for key, _mask in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(stream)
                    continue
                output, digest, size = streams[key.data]
                output.write(chunk)
                digest.update(chunk)
                streams[key.data] = (output, digest, size + len(chunk))
                if key.data == "stdout" and parser.feed(chunk):
                    deadline = time.monotonic() + grace
            if proc.poll() is not None and not events:
                # Pipes may still have buffered bytes; the next nonblocking
                # selector iteration drains them before their EOF is removed.
                continue
        attach_rc = proc.wait()
        resources.attach = None
        parser.finish()
        stream_receipt = {
            key: {"sha256": digest.hexdigest(), "size": size}
            for key, (_output, digest, size) in streams.items()
        }
    return attach_rc, progress.finish(), stream_receipt


def _stopped_state(doc: dict[str, Any]) -> dict[str, Any]:
    state = doc.get("State")
    if not isinstance(state, dict):
        raise Refusal("stopped candidate lacks Docker state")
    exit_code = state.get("ExitCode")
    pid = state.get("Pid")
    if (state.get("Status") != "exited" or state.get("Running") is not False
            or state.get("Paused") is not False
            or state.get("Restarting") is not False
            or state.get("OOMKilled") is not False
            or state.get("Dead") is not False
            or type(pid) is not int or pid != 0
            or type(exit_code) is not int or not 0 <= exit_code <= 255):
        raise Refusal("Docker did not prove a natural, non-OOM, dead-PID exit")
    error = state.get("Error")
    if error not in {None, ""}:
        raise Refusal("Docker recorded a candidate runtime error")
    return {
        "dead": False,
        "exit_code": exit_code,
        "oom_killed": False,
        "pid": 0,
        "pid_dead": True,
        "restarting": False,
        "running": False,
        "status": "exited",
    }


def _artefact_manifest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total = 0
    def walk_error(exc: OSError) -> None:
        raise Refusal(f"cannot enumerate candidate evidence: {exc}")

    for current, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=walk_error):
        base = Path(current)
        dirnames.sort()
        filenames.sort()
        for name in list(dirnames):
            item = base / name
            if not stat.S_ISDIR(item.lstat().st_mode):
                raise Refusal("candidate evidence contains a symlink/special directory")
        for name in filenames:
            item = base / name
            rel = item.relative_to(root).as_posix()
            _safe_rel(rel, "candidate artefact path")
            data, info = _read_regular(item)
            total += len(data)
            if len(files) >= MAX_ARTEFACT_FILES or total > MAX_ARTEFACT_BYTES:
                raise Refusal("candidate evidence exceeds its resource bound")
            files.append({
                "mode": "100755" if info.st_mode & 0o111 else "100644",
                "path": rel,
                "sha256": _sha256(data),
                "size": len(data),
            })
    payload = {"files": files, "schema": SCHEMA}
    return {
        "files": files,
        "total_bytes": total,
        "tree_sha256": _sha256(_canonical(payload)),
    }


def _strip_volume_ready_marker(root: Path) -> None:
    marker = root / _VOLUME_READY_MARKER
    try:
        info = marker.lstat()
    except FileNotFoundError:
        # The uid-65534 candidate may remove the seed marker.  Its purpose was
        # already complete before candidate create: making the standard volume
        # non-empty so Docker cannot re-copy destination metadata at /evidence.
        return
    if not stat.S_ISREG(info.st_mode) or info.st_size != 0:
        raise Refusal("candidate changed the evidence-volume provisioning marker")
    marker.unlink()


def _publish_stream_artifacts(root: Path, stdout_path: Path,
                              stderr_path: Path) -> None:
    for source, name in ((stdout_path, _STDOUT_ARTIFACT),
                         (stderr_path, _STDERR_ARTIFACT)):
        target = root / name
        if target.exists() or target.is_symlink():
            raise Refusal(f"candidate evidence occupied reserved stream {name}")
        data, _info = _read_regular(source)
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short stream-artifact write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)


def _prove_absent(docker: Docker, kind: str, name: str) -> None:
    proc = docker.call([kind, "inspect", name])
    error = proc.stderr.decode("utf-8", "replace").lower()
    expected = "no such container" if kind == "container" else "no such volume"
    if proc.returncode == 0 or expected not in error:
        raise Refusal(f"Docker did not prove removed {kind} {name!r} absent")


def _strict_remove(resources: Resources) -> dict[str, bool]:
    assert (resources.exporter is not None and resources.container is not None
            and resources.volume is not None)
    exporter = resources.exporter
    container = resources.container
    volume = resources.volume
    resources.docker.checked(["container", "rm", exporter],
                             "stopped evidence exporter removal")
    _prove_absent(resources.docker, "container", exporter)
    resources.exporter = None
    resources.docker.checked(["container", "rm", container],
                             "stopped candidate removal")
    _prove_absent(resources.docker, "container", container)
    resources.container = None
    resources.docker.checked(["volume", "rm", volume],
                             "private evidence volume removal")
    _prove_absent(resources.docker, "volume", volume)
    resources.volume = None
    return {
        "container_absent": True,
        "exporter_absent": True,
        "provisioner_absent": True,
        "volume_absent": True,
    }


def _publish_directory(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise Refusal("output directory already exists")
    parent = destination.parent.resolve(strict=True)
    staged = Path(tempfile.mkdtemp(prefix=".vibeic-evidence-", dir=parent))
    staged.rmdir()
    try:
        shutil.copytree(source, staged, symlinks=False)
        if _artefact_manifest(staged) != _artefact_manifest(source):
            raise Refusal("published candidate evidence changed during copy")
        if destination.exists() or destination.is_symlink():
            raise Refusal("output directory appeared during publication")
        os.rename(staged, destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Refusal("receipt path already exists")
    parent = path.parent.resolve(strict=True)
    payload = _canonical(receipt) + b"\n"
    fd, raw_tmp = tempfile.mkstemp(prefix=".vibeic-receipt-", dir=parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise Refusal("receipt path appeared during publication")
        os.rename(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _validate_digest_summary(value: Any, what: str, *, file: bool = False) -> None:
    keys = {"mode", "permissions", "sha256", "size"} if file else {
        "digest", "directories", "files", "total_bytes"
    }
    row = _exact_keys(value, keys, what)
    _hex64(row["sha256"] if file else row["digest"], f"{what} digest")
    if file and row["mode"] not in {"100644", "100755"}:
        raise ValueError(f"{what} mode differs")
    if (file and (not isinstance(row["permissions"], str)
                  or re.fullmatch(r"0[0-7]{3}", row["permissions"]) is None
                  or not int(row["permissions"], 8) & stat.S_IROTH)):
        raise ValueError(f"{what} permissions differ")
    for key in keys - {"mode", "permissions", "sha256", "digest"}:
        _exact_int(row[key], f"{what} {key}")


def validate_receipt(doc: Any) -> dict[str, Any]:
    receipt = _exact_keys(doc, {
        "artifacts", "cleanup", "container", "image", "inputs", "progress",
        "provisioner", "receipt_sha256", "result", "run_id", "runner", "schema",
        "streams", "transport", "volume",
    }, "hermetic candidate receipt")
    if type(receipt["schema"]) is not int or receipt["schema"] != SCHEMA:
        raise ValueError("receipt schema is unknown")
    if receipt["runner"] != "vibeic-hermetic-candidate-runner/v1":
        raise ValueError("receipt runner identity differs")
    run_id = _bounded_string(receipt["run_id"], "receipt run ID")
    if re.fullmatch(r"[0-9a-f]{24}", run_id) is None:
        raise ValueError("receipt run ID is malformed")
    image = _exact_keys(receipt["image"], {
        "id", "platform", "reference", "repo_digest"
    },
                        "receipt image")
    if (image["reference"] != IMAGE or image["repo_digest"] != IMAGE
            or image["platform"] != PLATFORM
            or not isinstance(image["id"], str)
            or not image["id"].startswith("sha256:")
            or _HEX64.fullmatch(image["id"][7:]) is None):
        raise ValueError("receipt image binding differs")
    volume = _exact_keys(receipt["volume"], {"driver", "name", "options"},
                         "receipt volume")
    if (volume["driver"] != "local"
            or volume["name"] != f"vibeic-candidate-evidence-{run_id}"
            or volume["options"] != {}):
        raise ValueError("receipt volume profile differs")
    provisioner = _exact_keys(receipt["provisioner"], {
        "cap_drop", "command", "container_id", "environment_sha256", "launcher",
        "mount", "network", "no_new_privileges", "read_only_rootfs", "removed",
        "restart", "result", "streams", "tmpfs", "user", "workdir",
    }, "receipt evidence volume provisioner")
    if (provisioner["cap_drop"] != ["ALL"]
            or provisioner["command"] != [
                "/usr/bin/touch", f"/var/tmp/{_VOLUME_READY_MARKER}"
            ]
            or provisioner["launcher"] != ["/usr/bin/env", "-i", "--"]
            or provisioner["network"] != "none"
            or provisioner["no_new_privileges"] is not True
            or provisioner["read_only_rootfs"] is not True
            or provisioner["removed"] is not True
            or provisioner["restart"] != "no"
            or provisioner["tmpfs"] != {
                "destination": "/tmp", "options": TMPFS_OPTIONS
            }
            or provisioner["user"] != USER or provisioner["workdir"] != "/"):
        raise ValueError("receipt evidence volume provisioner profile differs")
    if (not isinstance(provisioner["container_id"], str)
            or _CONTAINER_ID.fullmatch(provisioner["container_id"]) is None):
        raise ValueError("receipt evidence volume provisioner ID is malformed")
    _hex64(provisioner["environment_sha256"], "provisioner environment digest")
    if provisioner["mount"] != {
            "destination": "/var/tmp", "read_only": False,
            "role": "volume_metadata_copyup", "source": volume["name"],
            "type": "volume",
    }:
        raise ValueError("receipt evidence volume provisioner mount differs")
    clean_helper_result = {
        "attach_exit_code": 0, "dead": False, "exit_code": 0,
        "oom_killed": False, "pid": 0, "pid_dead": True,
        "restarting": False, "running": False, "status": "exited",
    }
    if provisioner["result"] != clean_helper_result:
        raise ValueError("receipt evidence volume provisioner result differs")
    provisioner_streams = _exact_keys(
        provisioner["streams"], {"stderr", "stdout"}, "provisioner streams")
    for key in ("stdout", "stderr"):
        row = _exact_keys(
            provisioner_streams[key], {"sha256", "size"}, f"provisioner {key}")
        _hex64(row["sha256"], f"provisioner {key} digest")
        _exact_int(row["size"], f"provisioner {key} size")
    container = _exact_keys(receipt["container"], {
        "cap_drop", "command", "container_id", "environment_sha256", "launcher", "mounts",
        "network", "no_new_privileges", "process_environment",
        "read_only_rootfs", "restart", "tmpfs", "user", "workdir",
    }, "receipt container")
    if (container["cap_drop"] != ["ALL"] or container["network"] != "none"
            or container["no_new_privileges"] is not True
            or container["read_only_rootfs"] is not True
            or container["restart"] != "no" or container["user"] != USER
            or container["launcher"] != ["/usr/bin/env", "-i", "--"]
            or container["workdir"] != WORKDIR
            or container["tmpfs"] != {
                "destination": "/tmp", "options": TMPFS_OPTIONS
            }):
        raise ValueError("receipt container profile differs")
    if (not isinstance(container["container_id"], str)
            or _CONTAINER_ID.fullmatch(container["container_id"]) is None):
        raise ValueError("receipt container ID is malformed")
    _hex64(container["environment_sha256"], "environment digest")
    receipt_process_env = _receipt_process_env(container["process_environment"])
    command = container["command"]
    if (not isinstance(command, list) or not command
            or not all(isinstance(arg, str) and "\0" not in arg for arg in command)):
        raise ValueError("receipt command is malformed")
    inputs = _exact_keys(receipt["inputs"], {
        "corpus", "overlays", "progress_plan", "runtime",
        "runtime_progress_plan", "selection", "subject"
    }, "receipt inputs")
    _validate_digest_summary(inputs["subject"], "subject")
    _validate_digest_summary(inputs["runtime"], "runtime")
    _validate_digest_summary(inputs["corpus"], "corpus")
    _validate_digest_summary(inputs["selection"], "selection", file=True)
    for key in ("progress_plan", "runtime_progress_plan"):
        row = _exact_keys(inputs[key], {"sha256", "size"}, key)
        _hex64(row["sha256"], f"{key} digest")
        _exact_int(row["size"], f"{key} size")
    overlay_inputs = inputs["overlays"]
    if not isinstance(overlay_inputs, list) or not overlay_inputs:
        raise ValueError("receipt runtime overlay manifest is empty/malformed")
    overlay_paths: list[str] = []
    overlay_destinations: dict[str, str] = {}
    for item in overlay_inputs:
        row = _exact_keys(item, {"destination", "path", "source_file"},
                          "receipt runtime overlay")
        path = _safe_rel(row["path"], "receipt runtime overlay path")
        destination = f"{WORKDIR}/{path}"
        if row["destination"] != destination:
            raise ValueError("receipt runtime overlay destination differs")
        _validate_digest_summary(row["source_file"], "runtime overlay", file=True)
        overlay_paths.append(path)
        overlay_destinations[destination] = path
    if overlay_paths != sorted(set(overlay_paths)):
        raise ValueError("receipt runtime overlays are not sorted/unique")
    if command[0] not in overlay_destinations:
        raise ValueError("receipt command is not a pre-authorized overlay")
    command_row = overlay_inputs[overlay_paths.index(overlay_destinations[command[0]])]
    if not int(command_row["source_file"]["permissions"], 8) & stat.S_IXOTH:
        raise ValueError("receipt overlay command is not executable by uid 65534")
    mounts = container["mounts"]
    if not isinstance(mounts, list) or len(mounts) != 6 + len(overlay_inputs):
        raise ValueError("receipt mount set differs")
    expected_mounts = {
        EVIDENCE_PATH: ("evidence", "volume", False),
        CORPUS_PATH: ("corpus", "bind", True),
        "/input/progress-plan.json": ("progress_plan", "bind", True),
        "/input/selection": ("selection", "bind", True),
        RUNTIME_ROOT: ("runtime", "bind", True),
        WORKDIR: ("subject", "bind", True),
    }
    for destination, path in overlay_destinations.items():
        expected_mounts[destination] = (f"runtime_overlay:{path}", "bind", True)
    destinations: list[str] = []
    mount_sources: dict[str, str] = {}
    for item in mounts:
        row = _exact_keys(item, {"destination", "read_only", "role", "source", "type"},
                          "receipt mount")
        dest = row["destination"]
        if dest not in expected_mounts:
            raise ValueError("receipt contains an unowned mount")
        role, kind, readonly = expected_mounts[dest]
        if (row["role"], row["type"], row["read_only"]) != (role, kind, readonly):
            raise ValueError("receipt mount profile differs")
        source = _bounded_string(row["source"], "receipt mount source")
        if "docker.sock" in source:
            raise ValueError("receipt exposes docker.sock")
        if role == "evidence" and source != volume["name"]:
            raise ValueError("receipt evidence mount differs from its volume")
        mount_sources[dest] = source
        destinations.append(dest)
    if destinations != sorted(expected_mounts):
        raise ValueError("receipt mounts are not canonical/exact")
    runtime_source = Path(mount_sources[RUNTIME_ROOT])
    if not runtime_source.is_absolute():
        raise ValueError("receipt runtime mount source is not absolute")
    for destination, path in overlay_destinations.items():
        expected_source = str(runtime_source.joinpath(*PurePosixPath(path).parts))
        if mount_sources[destination] != expected_source:
            raise ValueError("receipt runtime overlay source differs")
    transport = _exact_keys(receipt["transport"], {
        "cap_drop", "command", "container_id", "environment_sha256", "mounts",
        "network", "no_new_privileges", "read_only_rootfs", "restart", "result",
        "streams", "tmpfs", "user", "workdir",
    }, "receipt evidence transport")
    if (transport["cap_drop"] != ["ALL"] or transport["network"] != "none"
            or transport["no_new_privileges"] is not True
            or transport["read_only_rootfs"] is not True
            or transport["restart"] != "no" or transport["user"] != USER
            or transport["workdir"] != "/"
            or transport["tmpfs"] != {
                "destination": "/tmp", "options": TMPFS_OPTIONS
            }
            or transport["command"] != [
                "/bin/cp", "-R", "--no-preserve=mode,ownership",
                "/evidence/.", "/export/",
            ]):
        raise ValueError("receipt evidence transport profile differs")
    if (not isinstance(transport["container_id"], str)
            or _CONTAINER_ID.fullmatch(transport["container_id"]) is None):
        raise ValueError("receipt evidence transport ID is malformed")
    _hex64(transport["environment_sha256"], "transport environment digest")
    transport_mounts = transport["mounts"]
    if not isinstance(transport_mounts, list) or len(transport_mounts) != 2:
        raise ValueError("receipt evidence transport mounts differ")
    expected_transport_mounts = {
        "/evidence": ("evidence", "volume", True),
        "/export": ("post_stop_export", "bind", False),
    }
    transport_destinations: list[str] = []
    for item in transport_mounts:
        row = _exact_keys(item, {
            "destination", "read_only", "role", "source", "type"
        }, "receipt evidence transport mount")
        destination = row["destination"]
        if destination not in expected_transport_mounts:
            raise ValueError("receipt evidence transport has an unowned mount")
        role, kind, readonly = expected_transport_mounts[destination]
        if (row["role"], row["type"], row["read_only"]) != (
                role, kind, readonly):
            raise ValueError("receipt evidence transport mount profile differs")
        source = _bounded_string(row["source"], "transport mount source")
        if "docker.sock" in source:
            raise ValueError("receipt evidence transport exposes docker.sock")
        if role == "evidence" and source != volume["name"]:
            raise ValueError("receipt transport volume binding differs")
        transport_destinations.append(destination)
    if transport_destinations != sorted(expected_transport_mounts):
        raise ValueError("receipt evidence transport mounts are not canonical")
    progress = _exact_keys(receipt["progress"], {
        "completed", "protocol_sha256", "records", "scope", "total", "units"
    }, "receipt progress")
    units = progress["units"]
    if (not isinstance(units, list) or not units
            or len(units) != len(set(units))
            or not all(isinstance(unit, str) and unit for unit in units)):
        raise ValueError("receipt progress units differ")
    total = _exact_int(progress["total"], "progress total", 1)
    if (total != len(units) or progress["completed"] != total
            or progress["records"] != total + 2):
        raise ValueError("receipt progress is not complete")
    _bounded_string(progress["scope"], "receipt progress scope")
    if receipt_process_env["VIBEIC_HERMETIC_PROGRESS_SCOPE"] != progress["scope"]:
        raise ValueError("receipt progress scope differs from process environment")
    _hex64(progress["protocol_sha256"], "progress protocol digest")
    result = _exact_keys(receipt["result"], {
        "attach_exit_code", "dead", "exit_code", "oom_killed", "pid", "pid_dead",
        "restarting", "running", "status",
    }, "receipt result")
    exit_code = _exact_int(result["exit_code"], "candidate exit code", 0, 255)
    if (_exact_int(result["attach_exit_code"], "attach exit code", 0, 255)
            != exit_code or result != {
                "attach_exit_code": exit_code,
                "dead": False,
                "exit_code": exit_code,
                "oom_killed": False,
                "pid": 0,
                "pid_dead": True,
                "restarting": False,
                "running": False,
                "status": "exited",
            }):
        raise ValueError("receipt does not prove the exact stopped state")
    streams = _exact_keys(receipt["streams"], {"stderr", "stdout"},
                          "receipt streams")
    for key in ("stdout", "stderr"):
        row = _exact_keys(streams[key], {"sha256", "size"}, f"receipt {key}")
        _hex64(row["sha256"], f"receipt {key} digest")
        _exact_int(row["size"], f"receipt {key} size")
    transport_result = transport["result"]
    if transport_result != {
            "attach_exit_code": 0,
            "dead": False,
            "exit_code": 0,
            "oom_killed": False,
            "pid": 0,
            "pid_dead": True,
            "restarting": False,
            "running": False,
            "status": "exited",
    }:
        raise ValueError("receipt evidence transport did not exit cleanly")
    transport_streams = _exact_keys(
        transport["streams"], {"stderr", "stdout"}, "transport streams")
    for key in ("stdout", "stderr"):
        row = _exact_keys(
            transport_streams[key], {"sha256", "size"}, f"transport {key}")
        _hex64(row["sha256"], f"transport {key} digest")
        _exact_int(row["size"], f"transport {key} size")
    artifacts = _exact_keys(receipt["artifacts"], {
        "files", "total_bytes", "tree_sha256"
    }, "receipt artifacts")
    files = artifacts["files"]
    if not isinstance(files, list) or len(files) > MAX_ARTEFACT_FILES:
        raise ValueError("receipt artefact file list differs")
    observed_paths: list[str] = []
    observed_total = 0
    for item in files:
        row = _exact_keys(item, {"mode", "path", "sha256", "size"},
                          "receipt artefact")
        if row["mode"] not in {"100644", "100755"}:
            raise ValueError("receipt artefact mode differs")
        observed_paths.append(_safe_rel(row["path"], "receipt artefact path"))
        _hex64(row["sha256"], "receipt artefact digest")
        observed_total += _exact_int(row["size"], "receipt artefact size")
    if observed_paths != sorted(set(observed_paths)):
        raise ValueError("receipt artefact paths are not sorted/unique")
    if observed_total != artifacts["total_bytes"]:
        raise ValueError("receipt artefact byte total differs")
    expected_tree = _sha256(_canonical({"files": files, "schema": SCHEMA}))
    if artifacts["tree_sha256"] != expected_tree:
        raise ValueError("receipt artefact tree digest differs")
    artifact_by_path = {row["path"]: row for row in files}
    for stream_name, artifact_name in (
            ("stdout", _STDOUT_ARTIFACT), ("stderr", _STDERR_ARTIFACT)):
        row = artifact_by_path.get(artifact_name)
        if (row is None or row["sha256"] != streams[stream_name]["sha256"]
                or row["size"] != streams[stream_name]["size"]):
            raise ValueError("receipt stream artefact binding differs")
    if receipt["cleanup"] != {
            "container_absent": True,
            "exporter_absent": True,
            "provisioner_absent": True,
            "volume_absent": True,
    }:
        raise ValueError("receipt cleanup proof differs")
    body = dict(receipt)
    claimed = body.pop("receipt_sha256")
    _hex64(claimed, "receipt digest")
    if claimed != _sha256(_canonical(body)):
        raise ValueError("receipt digest differs")
    return receipt


def strict_load_receipt(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    doc = strict_loads(raw)
    receipt = validate_receipt(doc)
    if raw != _canonical(receipt) + b"\n":
        raise ValueError("receipt is not canonical JSON with one final newline")
    return receipt


def run(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command or any(not arg or "\0" in arg for arg in command):
        raise Refusal("a non-empty direct candidate command is required")
    command_path = PurePosixPath(command[0])
    if (not command_path.is_absolute() or ".." in command_path.parts
            or str(command_path) != command[0]):
        raise Refusal("candidate command must be a canonical absolute overlay path")
    output = args.output_dir.absolute()
    receipt_path = args.receipt.absolute()
    if output.exists() or output.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise Refusal("output directory and receipt must be new paths")
    output.parent.resolve(strict=True)
    receipt_path.parent.resolve(strict=True)
    home = _home_path()
    subject = _resolve_mount(args.subject, "subject", home)
    runtime = _resolve_mount(args.runtime, "runtime", home)
    corpus = _resolve_mount(args.corpus, "corpus", home)
    selection = _resolve_mount(args.selection, "selection", home)
    progress_path = _resolve_mount(args.progress_plan, "progress plan", home)
    overlays = _overlay_paths(args.overlay, runtime, subject)
    reviewed_env = _reviewed_process_env(args.env)
    overlay_commands = {row["destination"] for row in overlays}
    if command[0] not in overlay_commands:
        raise Refusal("candidate command[0] must name a pre-authorized /subject overlay")
    command_overlay = next(row for row in overlays
                           if row["destination"] == command[0])
    if not int(command_overlay["source_file"]["permissions"], 8) & stat.S_IXOTH:
        raise Refusal("candidate overlay command is not executable by uid 65534")
    for destination, label in ((output, "output directory"),
                               (receipt_path, "receipt")):
        if (_inside(destination, subject) or _inside(destination, runtime)
                or _inside(destination, corpus)):
            raise Refusal(f"{label} cannot mutate a mounted candidate input")
    if (_inside(receipt_path, output) or _inside(output, receipt_path)
            or receipt_path == output):
        raise Refusal("output directory and receipt paths overlap")
    initial_inputs = {
        "subject": _tree_digest(subject, "subject"),
        "runtime": _tree_digest(runtime, "runtime"),
        "corpus": _tree_digest(corpus, "corpus"),
        "selection": _file_digest(selection),
        "overlays": [{
            "destination": row["destination"],
            "path": row["path"],
            "source_file": row["source_file"],
        } for row in overlays],
    }
    plan, plan_summary = _load_progress_plan(progress_path)
    initial_inputs["progress_plan"] = plan_summary

    run_id = os.urandom(12).hex()
    container_name = f"vibeic-candidate-{run_id}"
    volume_name = f"vibeic-candidate-evidence-{run_id}"
    if _RUN_NAME.fullmatch(container_name) is None:
        raise AssertionError("internal candidate name is malformed")
    docker = Docker(args.docker_bin)
    resources = Resources(docker)
    runtime_dir = Path(tempfile.mkdtemp(prefix="vibeic-hermetic-", dir="/tmp"))
    artifacts_dir = runtime_dir / "artifacts"
    artifacts_dir.mkdir(mode=0o700)
    # The post-stop exporter runs as the same unprivileged identity as the
    # candidate.  Its only writable host path is this random, private transport
    # directory; it never sees HOME or the Docker socket.
    os.chmod(artifacts_dir, 0o777)
    stdout_path = runtime_dir / "stdout.bin"
    stderr_path = runtime_dir / "stderr.bin"
    nonce = os.urandom(32).hex()
    process_env = {
        **_fixed_process_env(reviewed_env["GATEKEEPER_VERIFY_ARM"]),
        **reviewed_env,
        "VIBEIC_HERMETIC_EVIDENCE_PATH": EVIDENCE_PATH,
        "VIBEIC_HERMETIC_PROGRESS_NONCE": nonce,
        "VIBEIC_HERMETIC_PROGRESS_PATH": "/input/progress-plan.json",
        "VIBEIC_HERMETIC_PROGRESS_PREFIX": PROGRESS_PREFIX.decode("ascii"),
        "VIBEIC_HERMETIC_PROGRESS_SCOPE": plan["scope"],
    }
    process_environment = [
        f"{name}={process_env[name]}" for name in sorted(process_env)
    ]
    runtime_plan = {
        "nonce": nonce,
        "protocol": "VIBEIC_PROGRESS/1",
        "schema": SCHEMA,
        "scope": plan["scope"],
        "units": plan["units"],
    }
    runtime_plan_raw = _canonical(runtime_plan) + b"\n"
    runtime_plan_path = runtime_dir / "progress-plan.json"
    runtime_plan_path.write_bytes(runtime_plan_raw)
    os.chmod(runtime_plan_path, 0o444)
    initial_inputs["runtime_progress_plan"] = {
        "sha256": _sha256(runtime_plan_raw),
        "size": len(runtime_plan_raw),
    }

    old_handlers: dict[int, Any] = {}

    def interrupted(signum: int, _frame: Any) -> None:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SignalExit(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupted)
    try:
        image = _image_profile(docker)
        volume = _volume_create(docker, volume_name, run_id)
        resources.volume = volume_name
        provisioner = _provision_volume(
            docker, resources, run_id=run_id, image=image, volume=volume_name)
        create_args = [
            "container", "create", "--pull=never",
            "--platform", PLATFORM,
            "--name", container_name,
            "--label", f"ai.vibeic.hermetic-run={run_id}",
            "--user", USER,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges=true",
            "--restart", "no",
            "--tmpfs", f"/tmp:{TMPFS_OPTIONS}",
            "--workdir", WORKDIR,
            # The pinned desktop image has a UI startup entrypoint and an
            # inherited Cmd.  Fixed-image /usr/bin/env clears both policies,
            # then execs the exact overlay command as PID 1.
            "--entrypoint", "/usr/bin/env",
            "--mount", _mount_arg(subject, WORKDIR, readonly=True),
            "--mount", _mount_arg(runtime, RUNTIME_ROOT, readonly=True),
            "--mount", _mount_arg(corpus, CORPUS_PATH, readonly=True),
            "--mount", _mount_arg(selection, "/input/selection", readonly=True),
            "--mount", _mount_arg(runtime_plan_path, "/input/progress-plan.json", readonly=True),
            "--mount", _mount_arg(volume_name, EVIDENCE_PATH,
                                   readonly=False, volume=True),
            *[
                part
                for overlay in overlays
                for part in (
                    "--mount",
                    _mount_arg(
                        overlay["source"], overlay["destination"], readonly=True),
                )
            ],
            IMAGE,
            "-i", "--", *process_environment, *command,
        ]
        raw_cid = docker.checked(create_args, "candidate container creation")
        cid = raw_cid.decode("ascii", "strict").strip()
        if _CONTAINER_ID.fullmatch(cid) is None:
            raise Refusal("Docker returned a malformed candidate container ID")
        resources.container = container_name
        created = _inspect_container(docker, container_name,
                                     "created candidate inspection")
        mounts = {
            "subject": subject,
            "runtime": runtime,
            "corpus": corpus,
            "selection": selection,
            "progress_plan": runtime_plan_path,
        }
        container_profile = _validate_container_profile(
            created, name=container_name, image=image, command=command,
            mounts=mounts, overlays=overlays, volume=volume_name,
            process_environment=process_environment,
        )
        if container_profile["container_id"] != cid:
            raise Refusal("created candidate ID differs from inspection")
        progress = Progress(nonce, plan["scope"], plan["units"])
        attach_rc, progress_receipt, streams = _run_monitored(
            docker, resources, container_name, progress,
            plan["stall_grace_seconds"], stdout_path, stderr_path,
        )
        stopped = _inspect_container(docker, container_name,
                                     "stopped candidate inspection")
        if stopped.get("Id") != cid or stopped.get("Image") != image["id"]:
            raise Refusal("stopped candidate identity changed")
        stopped_state = _stopped_state(stopped)
        if attach_rc != stopped_state["exit_code"]:
            raise Refusal("Docker attach exit differs from inspected candidate exit")

        # No host evidence path is mounted before the stopped-state proof
        # above.  A separately named, inspected least-privilege exporter now
        # mounts the candidate volume read-only and the private transport path
        # read-write.  The candidate remains stopped throughout.
        transport = _post_stop_export(
            docker, resources, run_id=run_id, image=image,
            volume=volume_name, destination=artifacts_dir,
        )
        after_export = _inspect_container(
            docker, container_name, "post-export stopped candidate inspection")
        if (after_export.get("Id") != cid or after_export.get("Image") != image["id"]
                or _stopped_state(after_export) != stopped_state):
            raise Refusal("candidate stopped-state proof changed during export")
        _strip_volume_ready_marker(artifacts_dir)
        _publish_stream_artifacts(artifacts_dir, stdout_path, stderr_path)
        artifacts = _artefact_manifest(artifacts_dir)

        final_inputs = {
            "subject": _tree_digest(subject, "subject"),
            "runtime": _tree_digest(runtime, "runtime"),
            "corpus": _tree_digest(corpus, "corpus"),
            "selection": _file_digest(selection),
            "progress_plan": _file_digest(progress_path),
        }
        if (final_inputs["subject"] != initial_inputs["subject"]
                or final_inputs["runtime"] != initial_inputs["runtime"]
                or final_inputs["corpus"] != initial_inputs["corpus"]
                or final_inputs["selection"] != initial_inputs["selection"]
                or final_inputs["progress_plan"]["sha256"] != plan_summary["sha256"]
                or final_inputs["progress_plan"]["size"] != plan_summary["size"]):
            raise Refusal("candidate input changed between pre-arm and stopped copy")

        cleanup = _strict_remove(resources)
        result = {**stopped_state, "attach_exit_code": attach_rc}
        body = {
            "artifacts": artifacts,
            "cleanup": cleanup,
            "container": container_profile,
            "image": image,
            "inputs": initial_inputs,
            "progress": progress_receipt,
            "provisioner": provisioner,
            "result": result,
            "run_id": run_id,
            "runner": "vibeic-hermetic-candidate-runner/v1",
            "schema": SCHEMA,
            "streams": streams,
            "transport": transport,
            "volume": volume,
        }
        receipt = {**body, "receipt_sha256": _sha256(_canonical(body))}
        validate_receipt(receipt)
        _publish_directory(artifacts_dir, output)
        _write_receipt(receipt_path, receipt)
        return 0 if stopped_state["exit_code"] == 0 else 1
    finally:
        # Keep signals ignored until Docker has proved our named resources
        # removed.  Otherwise a signal arriving on an unrelated refusal path,
        # or a second signal on the interruption path, could orphan them.
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            resources.cleanup_owned()
        finally:
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
            shutil.rmtree(runtime_dir, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="operation", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--docker-bin", default="docker")
    run_parser.add_argument("--subject", type=Path, required=True)
    run_parser.add_argument("--runtime", type=Path, required=True)
    run_parser.add_argument(
        "--overlay", action="append", required=True, metavar="REL",
        help="sorted runtime-relative regular file mounted over /subject/REL",
    )
    run_parser.add_argument(
        "--env", action="append", default=[], metavar="NAME=VALUE",
        help="sorted arm-conditional entry from the reviewed environment allowlist",
    )
    run_parser.add_argument("--corpus", type=Path, required=True)
    run_parser.add_argument("--selection", type=Path, required=True)
    run_parser.add_argument("--progress-plan", type=Path, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--receipt", type=Path, required=True)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    verify_parser = sub.add_parser("verify-receipt")
    verify_parser.add_argument("receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "verify-receipt":
            receipt = strict_load_receipt(args.receipt)
            print(receipt["receipt_sha256"])
            return 0
        return run(args)
    except SignalExit as exc:
        print(f"[NORECORD] hermetic candidate interrupted by signal {exc.signum}",
              file=sys.stderr)
        return 128 + exc.signum
    except (OSError, UnicodeError, ValueError, Refusal,
            json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"[NORECORD] hermetic candidate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
