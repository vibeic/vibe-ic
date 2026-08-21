#!/usr/bin/env python3
"""Index-bound finite input plans for the routed-DEF receipt checkers.

The routed-corpus owner invokes four Python checkers as independent children.
Their stdout is evidence, not liveness: a noisy checker can still be stuck and
a healthy checker can be silent while it parses a large layout.  This module
turns the *tracked bytes the checker will consume* into the ordered finite work
manifest understood by :mod:`_semantic_child_progress`.

The parent and direct child independently enumerate Git's index.  Every unit
names the stage-0 blob, logical path, byte count, and working-tree inode.  The
child then holds an ``O_NOFOLLOW`` descriptor, reads an exact finite number of
chunks, and verifies the Git blob hash before the bytes are made available to
the checker.  Population drift, a dirty input, symlink substitution, inode
replacement, truncation/growth, or a failed Git query therefore prevents the
terminal progress record and is reported by the owner as NORECORD.  None of
those conditions is translated into the checker's PASS/FAIL verdict.

This strict path is opt-in.  With no semantic progress environment the four
checkers keep their historical filesystem behaviour byte-for-byte.
"""
from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

import _semantic_child_progress as _semantic_progress


MAX_INPUT_FILES = 4096
MAX_TOTAL_INPUT_BYTES = 256 * 1024 * 1024
MAX_INDEX_ROWS = 65536
MAX_GIT_POPULATION_BYTES = 64 * 1024 * 1024
MAX_GIT_DIAGNOSTIC_BYTES = 64 * 1024


def _refuse(message: str) -> _semantic_progress.ProgressProtocolError:
    return _semantic_progress.ProgressProtocolError(message)


def _git_env() -> Dict[str, str]:
    """Return a locale-fixed Git environment with no ambient authority."""
    # GIT_INDEX_FILE, GIT_DIR/WORK_TREE, object alternates, replacement refs,
    # and injected config can all make two processes agree on something other
    # than the checkout named by ``-C``.  Semantic population proof must derive
    # from that checkout alone, so discard the entire Git-specific namespace
    # and add back only restrictive settings.
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LANG": "C",
        "LC_ALL": "C",
        # Resolve ``git`` only from the operating system's default command
        # directories.  An ambient PATH entry must not replace the index
        # authority with a look-alike executable shared by parent and child.
        "PATH": os.defpath,
    })
    return env


def _run_git(
        argv: Sequence[str], *,
        max_stdout_bytes: int = MAX_GIT_DIAGNOSTIC_BYTES,
) -> subprocess.CompletedProcess[bytes]:
    """Run one finite Git query without inventing an elapsed-time verdict."""
    try:
        result = subprocess.run(
            list(argv), capture_output=True, env=_git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise _refuse(f"routed checker Git population query failed: {exc}") from exc
    if (len(result.stdout) > max_stdout_bytes
            or len(result.stderr) > MAX_GIT_DIAGNOSTIC_BYTES):
        raise _refuse(
            "routed checker Git population response exceeded its finite "
            "resource bound")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-2000:].decode(
            "utf-8", "replace").strip()
        raise _refuse(
            "routed checker Git population query returned "
            f"{result.returncode}" + (f": {detail}" if detail else ""))
    return result


def _exact_path(path: Path, what: str) -> Path:
    """Return an absolute logical path only when no component is a symlink."""
    logical = Path(os.path.abspath(os.fspath(path)))
    try:
        resolved = logical.resolve(strict=True)
    except OSError as exc:
        raise _refuse(f"{what} is unavailable: {logical}: {exc}") from exc
    if resolved != logical:
        raise _refuse(f"{what} traverses a symlink: {logical}")
    return logical


def _path_text(raw: bytes, what: str) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _refuse(f"{what} is not UTF-8 and cannot name an exact unit") from exc
    if (not value or "\n" in value or "\r" in value
            or len(value.encode("utf-8")) > 8192):
        raise _refuse(f"{what} is not a bounded single-line path")
    return value


def _stat_identity(st: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


@dataclass(frozen=True)
class TrackedFile:
    """One regular, materialized stage-0 Git input."""

    root: Path
    path: Path
    relative: str
    repo_relative: str
    mode: str
    oid: str
    object_format: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @property
    def identity(self) -> Tuple[int, int, int, int, int]:
        return (self.device, self.inode, self.size,
                self.mtime_ns, self.ctime_ns)

    def prefix(self, role: str) -> str:
        if (not role or "\n" in role or "\r" in role
                or len(role.encode("utf-8")) > 512):
            raise _refuse("routed checker input role is not a bounded string")
        return (
            f"input:{role}:{self.relative}:mode:{self.mode}:git:{self.oid}:"
            f"dev:{self.device}:ino:{self.inode}:bytes:{self.size}:"
            f"mtime:{self.mtime_ns}:ctime:{self.ctime_ns}")

    def units(self, role: str) -> List[str]:
        chunks = max(
            1, (self.size + _semantic_progress.WORK_CHUNK_BYTES - 1)
            // _semantic_progress.WORK_CHUNK_BYTES)
        prefix = self.prefix(role)
        return ([f"{prefix}:chunk:{index}/{chunks}"
                 for index in range(1, chunks + 1)]
                + [f"{prefix}:verified"])

    def _hasher(self):
        if self.object_format not in ("sha1", "sha256"):
            raise _refuse(
                f"unsupported Git object format {self.object_format!r}")
        digest = hashlib.new(self.object_format)
        digest.update(f"blob {self.size}\0".encode("ascii"))
        return digest

    def read_verified(self, role: str,
                      progress: _semantic_progress.ChildProgress) -> bytes:
        """Read exact bytes from one held inode and checkpoint finite chunks."""
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise _refuse(f"tracked routed input cannot be opened: {self.path}: {exc}") from exc
        pieces: List[bytes] = []
        hasher = self._hasher()
        try:
            opened = os.fstat(descriptor)
            try:
                named = self.path.lstat()
            except OSError as exc:
                raise _refuse(
                    f"tracked routed input pathname disappeared: {self.path}: {exc}") from exc
            if (not stat.S_ISREG(opened.st_mode)
                    or not stat.S_ISREG(named.st_mode)
                    or _stat_identity(opened) != self.identity
                    or _stat_identity(named) != self.identity):
                raise _refuse(
                    f"tracked routed input identity changed before read: {self.path}")
            consumed = 0
            units = self.units(role)
            for unit in units[:-1]:
                want = min(
                    _semantic_progress.WORK_CHUNK_BYTES,
                    self.size - consumed)
                # A zero-byte regular file still owns one finite chunk.
                chunk: List[bytes] = []
                remaining = want
                while remaining:
                    part = os.read(descriptor, remaining)
                    if not part:
                        raise _refuse(
                            "tracked routed input ended before its manifest: "
                            f"{self.path}")
                    chunk.append(part)
                    remaining -= len(part)
                data = b"".join(chunk)
                pieces.append(data)
                hasher.update(data)
                consumed += len(data)
                progress.checkpoint(unit)
            if os.read(descriptor, 1):
                raise _refuse(
                    f"tracked routed input grew beyond its manifest: {self.path}")
            after = os.fstat(descriptor)
            try:
                named_after = self.path.lstat()
            except OSError as exc:
                raise _refuse(
                    f"tracked routed input pathname disappeared after read: "
                    f"{self.path}: {exc}") from exc
            if (_stat_identity(after) != self.identity
                    or _stat_identity(named_after) != self.identity
                    or not stat.S_ISREG(named_after.st_mode)):
                raise _refuse(
                    f"tracked routed input changed during read: {self.path}")
            if hasher.hexdigest() != self.oid:
                raise _refuse(
                    f"tracked routed input bytes differ from Git index blob: "
                    f"{self.repo_relative}")
            progress.checkpoint(units[-1])
            return b"".join(pieces)
        finally:
            os.close(descriptor)


class IndexSnapshot:
    """A strict stage-0 index snapshot beneath one logical root."""

    def __init__(self, root: Path):
        self.root = _exact_path(Path(root), "routed checker input root")
        top_result = _run_git([
            "git", "-C", str(self.root), "rev-parse", "--show-toplevel"])
        top_text = _path_text(
            top_result.stdout[:-1]
            if top_result.stdout.endswith(b"\n") else top_result.stdout,
            "Git checkout root")
        if not top_text:
            raise _refuse("Git returned an empty routed checker checkout root")
        self.repo = _exact_path(Path(top_text), "Git checkout root")
        try:
            prefix = self.root.relative_to(self.repo)
        except ValueError as exc:
            raise _refuse(
                f"routed checker root {self.root} escaped Git root {self.repo}") from exc
        format_result = _run_git([
            "git", "-C", str(self.repo), "rev-parse", "--show-object-format"])
        try:
            self.object_format = format_result.stdout.decode(
                "ascii", "strict").strip()
        except UnicodeDecodeError as exc:
            raise _refuse("Git object format response is not ASCII") from exc
        if self.object_format not in ("sha1", "sha256"):
            raise _refuse(
                f"unsupported Git object format {self.object_format!r}")
        pathspec = prefix.as_posix() if prefix.parts else "."
        listed = _run_git([
            "git", "-C", str(self.repo), "ls-files", "--stage", "-z",
            "--full-name", "--", pathspec],
            max_stdout_bytes=MAX_GIT_POPULATION_BYTES)
        self._entries: Dict[str, Tuple[str, str, str]] = {}
        prefix_posix = PurePosixPath(prefix.as_posix()) if prefix.parts else None
        for raw_row in listed.stdout.split(b"\0"):
            if not raw_row:
                continue
            try:
                raw_meta, raw_name = raw_row.split(b"\t", 1)
                mode_b, oid_b, stage_b = raw_meta.split()
            except ValueError as exc:
                raise _refuse("Git returned a malformed routed checker index row") from exc
            name = _path_text(raw_name, "Git index path")
            try:
                mode = mode_b.decode("ascii", "strict")
                oid = oid_b.decode("ascii", "strict")
                stage = stage_b.decode("ascii", "strict")
            except UnicodeDecodeError as exc:
                raise _refuse(
                    f"Git index metadata is not ASCII for {name}") from exc
            if stage != "0":
                raise _refuse(
                    f"routed checker index path is not stage 0: {name}")
            expected_oid_len = 40 if self.object_format == "sha1" else 64
            if (len(oid) != expected_oid_len
                    or any(ch not in "0123456789abcdef" for ch in oid)):
                raise _refuse(f"invalid Git blob id for routed input {name}")
            indexed = PurePosixPath(name)
            try:
                relative = (indexed.relative_to(prefix_posix)
                            if prefix_posix else indexed)
            except ValueError as exc:
                raise _refuse(
                    f"Git returned out-of-root routed input {name}") from exc
            rel_text = relative.as_posix()
            if rel_text in self._entries:
                raise _refuse(f"duplicate routed input index row {rel_text}")
            self._entries[rel_text] = (mode, oid, name)
            if len(self._entries) > MAX_INDEX_ROWS:
                raise _refuse(
                    f"routed checker index population exceeds "
                    f"{MAX_INDEX_ROWS} rows")

        population_digest = hashlib.sha256()
        population_digest.update(b"routed-checker-index-population-v1\0")
        for relative in sorted(self._entries):
            mode, oid, repo_relative = self._entries[relative]
            for field in (relative, mode, oid, repo_relative):
                encoded = field.encode("utf-8")
                population_digest.update(len(encoded).to_bytes(8, "big"))
                population_digest.update(encoded)
        self._population_digest = population_digest.hexdigest()

    @property
    def relative_paths(self) -> Tuple[str, ...]:
        return tuple(sorted(self._entries))

    def population_unit(self, label: str) -> str:
        """Bind even an empty selection to the exact checkout/index snapshot."""
        if (not label or "\n" in label or "\r" in label
                or len(label.encode("utf-8")) > 512):
            raise _refuse("routed checker population label is not bounded")
        root_stat = self.root.lstat()
        repo_stat = self.repo.lstat()
        if (not stat.S_ISDIR(root_stat.st_mode)
                or not stat.S_ISDIR(repo_stat.st_mode)):
            raise _refuse("routed checker checkout root stopped being a directory")
        prefix = self.root.relative_to(self.repo).as_posix()
        if ("\n" in prefix or "\r" in prefix
                or len(prefix.encode("utf-8")) > 8192):
            raise _refuse("routed checker checkout prefix is not bounded")
        return (
            f"population:{label}:root-dev:{root_stat.st_dev}:"
            f"root-ino:{root_stat.st_ino}:repo-dev:{repo_stat.st_dev}:"
            f"repo-ino:{repo_stat.st_ino}:prefix:{prefix or '.'}:"
            f"index-rows:{len(self._entries)}:"
            f"index-sha256:{self._population_digest}")

    def select(self, predicate: Callable[[str], bool],
               disk_paths: Iterable[Path], *, population: str) -> List[TrackedFile]:
        """Bind a predicate's exact indexed and on-disk populations."""
        selected = sorted(rel for rel in self._entries if predicate(rel))
        disk: Dict[str, Path] = {}
        disk_order: List[str] = []
        for candidate in disk_paths:
            logical = Path(os.path.abspath(os.fspath(candidate)))
            try:
                relative = logical.relative_to(self.root).as_posix()
            except ValueError as exc:
                raise _refuse(
                    f"{population} disk candidate escaped input root: {logical}") from exc
            if relative in disk:
                continue
            disk[relative] = logical
            disk_order.append(relative)
        if sorted(disk) != selected:
            missing = sorted(set(selected) - set(disk))[:8]
            extra = sorted(set(disk) - set(selected))[:8]
            raise _refuse(
                f"{population} differs between Git index and working tree; "
                f"missing={missing}, untracked_or_unselected={extra}")
        out: List[TrackedFile] = []
        # Caller order is part of the checker's historical output (several
        # discoverers intentionally prefer sign-off GDS before routed DEF).
        # The exact-set comparison above proves it is still the same index
        # population; retain that deterministic caller order for execution.
        for relative in disk_order:
            mode, oid, repo_relative = self._entries[relative]
            if mode not in ("100644", "100755"):
                raise _refuse(
                    f"{population} publishes non-regular mode {mode}: {relative}")
            path = disk[relative]
            # Reject a symlink in every path component, not merely at the leaf.
            cursor = self.root
            for part in PurePosixPath(relative).parts:
                cursor = cursor / part
                try:
                    observed = cursor.lstat()
                except OSError as exc:
                    raise _refuse(
                        f"{population} path is not materialized: {cursor}: {exc}") from exc
                if stat.S_ISLNK(observed.st_mode):
                    raise _refuse(f"{population} traverses a symlink: {cursor}")
            st = path.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_size < 0
                    or st.st_size > _semantic_progress.MAX_WORK_FILE_BYTES):
                raise _refuse(
                    f"{population} input is outside the regular 0.."
                    f"{_semantic_progress.MAX_WORK_FILE_BYTES} byte bound: {path}")
            out.append(TrackedFile(
                self.root, path, relative, repo_relative, mode, oid,
                self.object_format, st.st_dev, st.st_ino, st.st_size,
                st.st_mtime_ns, st.st_ctime_ns))
        return out


@dataclass(frozen=True)
class PlannedRead:
    role: str
    tracked: TrackedFile


class FiniteInputPlan:
    """Ordered parent manifest plus child-side verified byte cache."""

    def __init__(self, population_units: Sequence[str],
                 reads: Sequence[PlannedRead],
                 decision_units: Sequence[str] = ("decision:computed",)):
        self.population_units = tuple(population_units)
        self.reads = tuple(reads)
        self.decision_units = tuple(decision_units)
        if len(self.reads) > MAX_INPUT_FILES:
            raise _refuse(
                f"routed checker input count exceeds {MAX_INPUT_FILES}")
        total_bytes = sum(item.tracked.size for item in self.reads)
        if total_bytes > MAX_TOTAL_INPUT_BYTES:
            raise _refuse(
                f"routed checker aggregate input exceeds {MAX_TOTAL_INPUT_BYTES} bytes")
        keys = [(item.role, item.tracked.path) for item in self.reads]
        if len(keys) != len(set(keys)):
            raise _refuse("routed checker plan repeats an input role/path")
        self._bytes: Dict[Tuple[str, Path], bytes] = {}
        self._by_path: Dict[Path, bytes] = {}
        self._progress: _semantic_progress.ChildProgress | None = None
        units = self.units
        if len(units) != len(set(units)):
            raise _refuse("routed checker finite manifest repeats a unit")

    @property
    def units(self) -> List[str]:
        out = list(self.population_units)
        for item in self.reads:
            out.extend(item.tracked.units(item.role))
        out.extend(self.decision_units)
        return out

    def materialize(self, progress: _semantic_progress.ChildProgress) -> None:
        self._progress = progress
        for unit in self.population_units:
            progress.checkpoint(unit)
        for item in self.reads:
            payload = item.tracked.read_verified(item.role, progress)
            self._bytes[(item.role, item.tracked.path)] = payload
            prior = self._by_path.setdefault(item.tracked.path, payload)
            if prior != payload:
                raise _refuse(
                    f"routed checker duplicate input changed: {item.tracked.path}")

    def checkpoint_decision(
            self, unit: str = "decision:computed", *,
            fresh_plan: "FiniteInputPlan | None" = None) -> None:
        if self._progress is None:
            raise _refuse("routed checker decision preceded input materialization")
        if fresh_plan is not None and fresh_plan.units != self.units:
            raise _refuse(
                "routed checker input population or identity changed while "
                "the decision was being computed")
        self._progress.checkpoint(unit)

    def paths(self, role: str) -> List[Path]:
        return [item.tracked.path for item in self.reads if item.role == role]

    def contains(self, path: Path) -> bool:
        return Path(os.path.abspath(os.fspath(path))) in self._by_path

    def bytes_for(self, path: Path) -> bytes:
        logical = Path(os.path.abspath(os.fspath(path)))
        try:
            return self._by_path[logical]
        except KeyError as exc:
            raise _refuse(
                f"checker attempted to read an input outside its parent plan: {logical}") from exc

    def text_for(self, path: Path, *, encoding: str | None = None,
                 errors: str = "strict") -> str:
        payload = self.bytes_for(path)
        # TextIOWrapper matches Path.open/read_text newline translation and its
        # locale-default encoding when callers historically omitted encoding.
        with io.TextIOWrapper(io.BytesIO(payload), encoding=encoding,
                              errors=errors, newline=None) as stream:
            return stream.read()


def planned_reads(role: str, files: Sequence[TrackedFile]) -> List[PlannedRead]:
    return [PlannedRead(role, item) for item in files]


def disk_files(root: Path, predicate: Callable[[Path], bool]) -> List[Path]:
    """Stable non-directory-symlink-following disk population beneath root."""
    root = Path(root)
    out: List[Path] = []
    for parent, dirnames, filenames in os.walk(root, followlinks=False):
        # A symlinked directory is not followed by os.walk; retain it nowhere.
        # If Git expects content below it, IndexSnapshot.select reports missing.
        dirnames.sort()
        filenames.sort()
        base = Path(parent)
        for name in filenames:
            candidate = base / name
            if predicate(candidate):
                out.append(candidate)
    return out
