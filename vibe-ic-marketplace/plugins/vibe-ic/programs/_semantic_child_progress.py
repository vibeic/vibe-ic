#!/usr/bin/env python3
"""Strict finite-work progress between one child and its owning supervisor.

This is a liveness protocol, not a stream of reassuring text.  The supervisor
owns an exact ordered manifest of finite work units and a random nonce.  The
direct child records one append-only JSON line for the FSM

    start -> checkpoint(unit 1) .. checkpoint(unit N) -> terminal

and nothing else.  Only a newly completed, manifest-matching unit is forward
progress.  Output bytes, CPU activity, repeated events and the terminal marker
do not renew the lease.  The protocol has no elapsed-runtime ceiling; the
supervisor may therefore wait arbitrarily long while real units continue to
complete.

The stall grace is an operational recording lease, never a correctness
verdict: expiry yields NORECORD.  Corpus files are split into size-bound byte
chunks plus a judgement unit, so a large but healthy document can keep proving
finite work instead of being treated as one opaque 300-second operation.  A
single chunk that cannot complete before the lease still yields NORECORD; time
is never translated into FAIL/PASS or used as a total-runtime estimate.

When the four issue-1710 checkers are invoked normally, none of the environment
variables below exists and :func:`child_progress` is a byte-for-byte no-op.
The strict channel is opt-in by the owning parent.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from _atomic_artefact import write_json

SCHEMA = 1
ENV_PATH = "VIBE_IC_CHILD_PROGRESS_PATH"
ENV_NONCE = "VIBE_IC_CHILD_PROGRESS_NONCE"
ENV_SCOPE = "VIBE_IC_CHILD_PROGRESS_SCOPE"
ENV_TOTAL = "VIBE_IC_CHILD_PROGRESS_TOTAL"
ENV_DEVICE = "VIBE_IC_CHILD_PROGRESS_DEVICE"
ENV_INODE = "VIBE_IC_CHILD_PROGRESS_INODE"
ENV_KEYS = (ENV_PATH, ENV_NONCE, ENV_SCOPE, ENV_TOTAL, ENV_DEVICE, ENV_INODE)

_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PROTOCOL_BYTES = 64 * 1024 * 1024
_MAX_IDENTITY_BYTES = 16 * 1024
WORK_CHUNK_BYTES = 256 * 1024
MAX_WORK_FILE_BYTES = 64 * 1024 * 1024
ProgressNotifier = Callable[[str, int, int], None]


class ProgressProtocolError(ValueError):
    """The semantic progress record cannot certify the child's liveness."""


def _strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProgressProtocolError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _reject_constant(token: str):
    raise ProgressProtocolError(f"non-finite JSON number {token!r}")


def strict_loads(payload: str):
    """Parse one unambiguous JSON value (duplicates/NaN/Infinity refuse)."""
    return json.loads(payload, object_pairs_hook=_strict_object,
                      parse_constant=_reject_constant)


def _exact_int(value, what: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProgressProtocolError(
            f"{what} must be an integer >= {minimum}, got {value!r}")
    return value


def _identity(value, what: str) -> str:
    if (not isinstance(value, str) or not value or "\n" in value
            or "\r" in value
            or len(value.encode("utf-8")) > _MAX_IDENTITY_BYTES):
        raise ProgressProtocolError(f"{what} is not a bounded exact string")
    return value


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _projected_channel_bytes(nonce: str, scope: str,
                             units: Sequence[str]) -> int:
    """Conservative exact-row budget with a maximum signed PID width."""
    pid = (1 << 63) - 1
    total = len(units)
    common = {"schema": SCHEMA, "nonce": nonce, "pid": pid,
              "scope": scope, "total": total}
    def wire_size(row: dict) -> int:
        return len((json.dumps(row, sort_keys=True, ensure_ascii=True,
                               separators=(",", ":")) + "\n").encode("ascii"))

    projected = wire_size({**common, "seq": 0, "state": "start"})
    for index, unit in enumerate(units, 1):
        projected += wire_size({
            **common, "seq": index, "state": "checkpoint",
            "completed": index, "unit": unit,
        })
        if projected > _MAX_PROTOCOL_BYTES:
            return projected
    return projected + wire_size({
        **common, "seq": total + 1, "state": "terminal",
        "completed": total,
    })


def file_progress_units(path: Path, identity: str) -> List[str]:
    """Finite chunk manifest for one bounded corpus file plus its judgement.

    Runtime is never bounded.  Input size is: an indivisible parser over an
    unbounded file could otherwise remain healthy for longer than any finite
    stall lease without being able to prove semantic progress.  Larger inputs
    are therefore NORECORD at manifest construction, not a gate verdict.
    """
    identity = _identity(identity, "corpus file identity")
    try:
        file_stat = Path(path).stat()
    except OSError as exc:
        raise ProgressProtocolError(
            f"cannot size corpus progress file {path}: {exc}") from exc
    size = file_stat.st_size
    if (not stat.S_ISREG(file_stat.st_mode) or type(size) is not int
            or size < 0 or size > MAX_WORK_FILE_BYTES):
        raise ProgressProtocolError(
            f"corpus progress file {path} is outside the 0.."
            f"{MAX_WORK_FILE_BYTES} byte resource bound")
    chunks = max(1, (size + WORK_CHUNK_BYTES - 1) // WORK_CHUNK_BYTES)
    bound = f"{identity}:bytes:{size}"
    return ([f"{bound}:chunk:{index}/{chunks}"
             for index in range(1, chunks + 1)]
            + [f"{bound}:judged"])


def file_judged_unit(path: Path, identity: str) -> str:
    """Return the size-bound terminal unit after a file has been judged."""
    return file_progress_units(path, identity)[-1]


def read_text_chunks(path: Path, identity: str,
                     progress: Optional["ChildProgress"], *,
                     encoding: str = "utf-8", errors: str = "replace") -> str:
    """Read a corpus file in exact finite chunks, checkpointing each chunk.

    With progress disabled this delegates to ``Path.read_text`` so ordinary
    checker behaviour stays unchanged.  The final ``:judged`` unit belongs to
    the caller and must be emitted only after its parser/rule has consumed the
    returned text.
    """
    path = Path(path)
    if progress is None or not progress.enabled:
        return path.read_text(encoding=encoding, errors=errors)
    planned_size = path.stat().st_size
    units = file_progress_units(path, identity)
    chunks = units[:-1]
    pieces = []
    with path.open("rb") as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_size != planned_size
                or st.st_size < 0
                or st.st_size > MAX_WORK_FILE_BYTES):
            raise ProgressProtocolError(
                f"corpus progress file {path} changed outside its resource bound")
        expected_size = st.st_size
        consumed = 0
        for unit in chunks:
            want = min(WORK_CHUNK_BYTES, expected_size - consumed)
            data = stream.read(want)
            if len(data) != want:
                raise ProgressProtocolError(
                    f"corpus progress file {path} ended before its manifest")
            pieces.append(data)
            consumed += len(data)
            progress.checkpoint(unit)
        if stream.read(1):
            raise ProgressProtocolError(
                f"corpus progress file {path} grew beyond its manifest")
    return b"".join(pieces).decode(encoding, errors)


@dataclass(frozen=True)
class ParentPlan:
    """Files and child environment for one parent-owned progress channel."""

    manifest_path: Path
    progress_path: Path
    nonce: str
    scope: str
    units: Tuple[str, ...]
    env: Dict[str, str]


def prepare_parent(directory: Path, scope: str, units: Sequence[str],
                   env: Dict[str, str]) -> ParentPlan:
    """Create a private channel and immutable-in-memory finite manifest.

    There is deliberately no maximum unit *count*.  The serialized manifest
    and each identity have byte resource bounds, but runtime is never inferred
    from the number of units.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    scope = _identity(scope, "progress scope")
    exact_units = tuple(_identity(unit, "progress unit") for unit in units)
    if len(set(exact_units)) != len(exact_units):
        raise ProgressProtocolError("parent progress manifest repeats a unit")
    nonce = secrets.token_hex(32)
    if _projected_channel_bytes(nonce, scope, exact_units) > _MAX_PROTOCOL_BYTES:
        raise ProgressProtocolError(
            "finite semantic progress journal exceeds its resource bound")
    progress_path = (directory / "semantic-child-progress.jsonl").resolve()
    manifest_path = (directory / "semantic-child-manifest.json").resolve()
    fd = os.open(progress_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    os.chmod(progress_path, stat.S_IRUSR | stat.S_IWUSR)
    channel_stat = progress_path.stat()
    if channel_stat.st_size != 0:
        raise ProgressProtocolError("new semantic progress channel is not empty")
    manifest = {
        "schema": SCHEMA,
        "nonce": nonce,
        "scope": scope,
        "units": list(exact_units),
        "path": str(progress_path),
        "device": channel_stat.st_dev,
        "inode": channel_stat.st_ino,
        "initial_size": 0,
    }
    encoded = _canonical(manifest).encode("utf-8")
    if len(encoded) > _MAX_PROTOCOL_BYTES:
        raise ProgressProtocolError(
            "parent progress manifest exceeds the protocol resource bound")
    write_json(manifest_path, manifest, ensure_ascii=False)
    os.chmod(manifest_path, stat.S_IRUSR | stat.S_IWUSR)
    child_env = dict(env)
    child_env.update({
        ENV_PATH: str(progress_path),
        ENV_NONCE: nonce,
        ENV_SCOPE: scope,
        ENV_TOTAL: str(len(exact_units)),
        ENV_DEVICE: str(channel_stat.st_dev),
        ENV_INODE: str(channel_stat.st_ino),
    })
    return ParentPlan(manifest_path, progress_path, nonce, scope,
                      exact_units, child_env)


def load_parent_manifest(path: Path) -> dict:
    """Load the exact parent sidecar before the child is launched."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        doc = strict_loads(raw)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ProgressProtocolError(
            f"unreadable semantic progress manifest: {exc}") from exc
    if not isinstance(doc, dict) or set(doc) != {
            "schema", "nonce", "scope", "units", "path", "device",
            "inode", "initial_size"}:
        raise ProgressProtocolError("semantic progress manifest schema differs")
    if type(doc.get("schema")) is not int or doc["schema"] != SCHEMA:
        raise ProgressProtocolError("unknown semantic progress manifest schema")
    nonce = doc.get("nonce")
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise ProgressProtocolError("semantic progress manifest nonce is invalid")
    scope = _identity(doc.get("scope"), "progress scope")
    units = doc.get("units")
    if not isinstance(units, list):
        raise ProgressProtocolError("semantic progress manifest units are not a list")
    exact = [_identity(unit, "progress unit") for unit in units]
    if len(exact) != len(set(exact)):
        raise ProgressProtocolError("semantic progress manifest repeats a unit")
    raw_path = doc.get("path")
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        raise ProgressProtocolError("semantic progress path is not absolute")
    if len(raw.encode("utf-8")) > _MAX_PROTOCOL_BYTES:
        raise ProgressProtocolError("semantic progress manifest exceeds resource bound")
    device = _exact_int(doc.get("device"), "progress channel device")
    inode = _exact_int(doc.get("inode"), "progress channel inode", minimum=1)
    if type(doc.get("initial_size")) is not int or doc["initial_size"] != 0:
        raise ProgressProtocolError("progress channel initial size is not zero")
    return {"nonce": nonce, "scope": scope, "units": tuple(exact),
            "path": Path(raw_path), "identity": (device, inode)}


class ParentMonitor:
    """Strictly validate an append-only child FSM and expose completed units."""

    def __init__(self, path: Path, nonce: str, scope: str,
                 units: Sequence[str], notifier: Optional[ProgressNotifier] = None,
                 expected_identity: Optional[Tuple[int, int]] = None):
        self.path = Path(path)
        self.nonce = nonce
        self.scope = scope
        self.units = tuple(units)
        self.notifier = notifier
        self.pid: Optional[int] = None
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        opened: Optional[int] = None
        try:
            opened = os.open(self.path, flags)
            initial = os.fstat(opened)
        except OSError as exc:
            if opened is not None:
                os.close(opened)
            raise ProgressProtocolError(
                f"semantic progress channel unavailable before launch: {exc}") from exc
        self.fd: Optional[int] = opened
        if (not stat.S_ISREG(initial.st_mode)
                or stat.S_IMODE(initial.st_mode) & 0o077):
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "semantic progress channel is not a private regular file")
        observed = (initial.st_dev, initial.st_ino)
        if expected_identity is not None and observed != expected_identity:
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "semantic progress channel identity changed before launch")
        if initial.st_size != 0:
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "semantic progress channel was not empty before launch")
        self.identity: Tuple[int, int] = observed
        self.rows: List[str] = []
        self.raw_seen = b""
        self.size = 0
        self.completed = 0
        self.error = ""

    @classmethod
    def from_manifest(cls, path: Path,
                      notifier: Optional[ProgressNotifier] = None
                      ) -> "ParentMonitor":
        doc = load_parent_manifest(path)
        return cls(doc["path"], doc["nonce"], doc["scope"], doc["units"],
                   notifier, doc["identity"])

    def bind_pid(self, pid: int) -> None:
        pid = _exact_int(pid, "direct child pid", minimum=1)
        if self.pid is not None and self.pid != pid:
            self._fail("semantic progress monitor was rebound to another PID")
            return
        self.pid = pid

    def _fail(self, reason: str) -> None:
        if not self.error:
            self.error = reason

    def _expected(self, index: int) -> dict:
        total = len(self.units)
        common = {
            "schema": SCHEMA, "nonce": self.nonce, "pid": self.pid,
            "seq": index, "scope": self.scope, "total": total,
        }
        if index == 0:
            return {**common, "state": "start"}
        if 1 <= index <= total:
            return {
                **common, "state": "checkpoint", "completed": index,
                "unit": self.units[index - 1],
            }
        if index == total + 1:
            return {**common, "state": "terminal", "completed": total}
        raise ProgressProtocolError("semantic progress has excess records")

    def sample(self, *, final: bool = False) -> int:
        """Return completed units; malformed state freezes until NORECORD."""
        if self.error:
            return self.completed
        if self.pid is None:
            return self.completed
        if self.fd is None:
            self._fail("semantic progress channel is closed")
            return self.completed
        try:
            # Keep the descriptor opened by the trusted helper before launch.
            # The pathname check detects unlink/replace, while fstat+pread on
            # the held fd prevents a stat->open substitution race.
            st = os.fstat(self.fd)
            path_st = self.path.lstat()
        except FileNotFoundError:
            self._fail("semantic progress channel disappeared")
            return self.completed
        except OSError as exc:
            self._fail(f"semantic progress channel is unreadable: {exc}")
            return self.completed
        observed = (st.st_dev, st.st_ino)
        path_observed = (path_st.st_dev, path_st.st_ino)
        if (not stat.S_ISREG(path_st.st_mode)
                or observed != self.identity or path_observed != self.identity):
            self._fail("semantic progress channel identity changed")
            return self.completed
        if (not stat.S_ISREG(st.st_mode)
                or stat.S_IMODE(st.st_mode) & 0o077):
            self._fail("semantic progress channel stopped being private")
            return self.completed
        if st.st_size < self.size:
            self._fail("semantic progress channel was truncated")
            return self.completed
        if st.st_size > _MAX_PROTOCOL_BYTES:
            self._fail("semantic progress channel exceeds resource bound")
            return self.completed
        try:
            raw = os.pread(self.fd, st.st_size, 0)
            if len(raw) != st.st_size:
                raise ProgressProtocolError(
                    "semantic progress channel changed during its snapshot")
            if not raw.startswith(self.raw_seen):
                raise ProgressProtocolError(
                    "semantic progress byte history was rewritten")
            complete, separator, tail = raw.rpartition(b"\n")
            if not separator:
                complete, tail = b"", raw
            if final and tail:
                raise ProgressProtocolError("truncated final progress record")
            parsed = []
            for lineno, line in enumerate(complete.splitlines(), 1):
                if not line:
                    raise ProgressProtocolError(
                        f"empty semantic progress line {lineno}")
                row = strict_loads(line.decode("utf-8"))
                if not isinstance(row, dict):
                    raise ProgressProtocolError(
                        f"semantic progress line {lineno} is not an object")
                # bool is an int subclass; exact equality alone would accept it
                # for 0/1, so all numeric protocol fields are typed explicitly.
                for field in ("schema", "pid", "seq", "total"):
                    _exact_int(row.get(field), f"progress line {lineno} {field}")
                if "completed" in row:
                    _exact_int(row["completed"],
                               f"progress line {lineno} completed")
                expected = self._expected(lineno - 1)
                if row != expected:
                    raise ProgressProtocolError(
                        f"semantic progress line {lineno} differs from the "
                        "parent-owned FSM/manifest")
                parsed.append(_canonical(row))
        except (OSError, UnicodeError, ValueError, TypeError,
                json.JSONDecodeError) as exc:
            self._fail(f"invalid semantic progress protocol: {exc}")
            return self.completed
        if parsed[:len(self.rows)] != self.rows:
            self._fail("semantic progress history was rewritten")
            return self.completed
        if len(parsed) < len(self.rows):
            self._fail("semantic progress history regressed")
            return self.completed
        old_completed = self.completed
        self.rows = parsed
        self.raw_seen = raw
        self.size = st.st_size
        self.completed = min(len(self.units), max(0, len(parsed) - 1))
        # Terminal is not a completion and never renews the lease.  Relay each
        # newly validated unit exactly once and in manifest order.
        if self.notifier is not None:
            for completed in range(old_completed + 1, self.completed + 1):
                try:
                    self.notifier(self.scope, completed, len(self.units))
                except Exception as exc:  # callback failure is protocol failure
                    self._fail(
                        "semantic progress notifier failed: "
                        f"{type(exc).__name__}: {exc}")
                    break
        return self.completed

    def complete(self) -> str:
        try:
            self.sample(final=True)
            if not self.error and len(self.rows) != len(self.units) + 2:
                self._fail(
                    "semantic progress ended without its exact terminal FSM record")
            return self.error
        finally:
            self.close()

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class RelayValidator:
    """Revalidate helper relays before calling the enclosing test lease."""

    def __init__(self, scope: str, total: int,
                 callback: Optional[ProgressNotifier]):
        self.scope = _identity(scope, "relay scope")
        self.total = _exact_int(total, "relay total")
        self.callback = callback
        self.completed = 0
        self.error = ""

    def accept(self, event: object) -> None:
        if self.error:
            return
        fields = {"protocol", "state", "scope", "completed", "total"}
        if not isinstance(event, dict) or set(event) != fields:
            self.error = "domain-progress relay has the wrong schema"
            return
        try:
            protocol = _exact_int(event.get("protocol"), "relay protocol")
            completed = _exact_int(event.get("completed"), "relay completed",
                                   minimum=1)
            total = _exact_int(event.get("total"), "relay total")
        except ProgressProtocolError as exc:
            self.error = str(exc)
            return
        if (protocol != SCHEMA or event.get("state") != "domain_progress"
                or event.get("scope") != self.scope or total != self.total
                or completed != self.completed + 1 or completed > total):
            self.error = "domain-progress relay is non-monotonic or unbound"
            return
        if self.callback is not None:
            try:
                self.callback(self.scope, completed, total)
            except Exception as exc:
                self.error = (
                    "domain-progress callback failed: "
                    f"{type(exc).__name__}: {exc}")
                return
        self.completed = completed


class ChildProgress:
    """Direct-child writer. Disabled only when all protocol env is absent."""

    def __init__(self, scope: str):
        present = [key in os.environ for key in ENV_KEYS]
        self.enabled = any(present)
        self.fd: Optional[int] = None
        self.completed = 0
        self.seen = set()
        self.pid = os.getpid()
        self.scope = scope
        self.nonce = ""
        self.total = 0
        self.seq = 0
        if not self.enabled:
            return
        if not all(present):
            raise ProgressProtocolError(
                "semantic child progress environment is incomplete")
        expected_scope = _identity(os.environ[ENV_SCOPE], "child scope")
        if _identity(scope, "checker progress scope") != expected_scope:
            raise ProgressProtocolError(
                f"checker scope {scope!r} differs from parent {expected_scope!r}")
        nonce = os.environ[ENV_NONCE]
        if _NONCE.fullmatch(nonce) is None:
            raise ProgressProtocolError("child progress nonce is invalid")
        raw_total = os.environ[ENV_TOTAL]
        try:
            total = int(raw_total)
        except ValueError as exc:
            raise ProgressProtocolError("child progress total is not an integer") from exc
        if total < 0 or str(total) != raw_total:
            raise ProgressProtocolError("child progress total is not canonical")
        raw_device = os.environ[ENV_DEVICE]
        raw_inode = os.environ[ENV_INODE]
        try:
            expected_device = int(raw_device)
            expected_inode = int(raw_inode)
        except ValueError as exc:
            raise ProgressProtocolError(
                "child progress identity is not integer-valued") from exc
        if (expected_device < 0 or expected_inode < 1
                or str(expected_device) != raw_device
                or str(expected_inode) != raw_inode):
            raise ProgressProtocolError(
                "child progress identity is not canonical")
        path = Path(os.environ[ENV_PATH])
        if not path.is_absolute():
            raise ProgressProtocolError("child progress path is not absolute")
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        self.fd = os.open(path, flags)
        st = os.fstat(self.fd)
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "child progress channel is not a private regular file")
        if (st.st_dev, st.st_ino) != (expected_device, expected_inode):
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "child progress channel differs from the parent identity")
        if st.st_size != 0:
            os.close(self.fd)
            self.fd = None
            raise ProgressProtocolError(
                "child progress channel was not empty at start")
        self.scope, self.nonce, self.total = scope, nonce, total

    def _emit(self, row: dict) -> None:
        if not self.enabled:
            return
        if self.fd is None:
            raise ProgressProtocolError("semantic progress channel is closed")
        payload = (json.dumps(row, sort_keys=True, ensure_ascii=True,
                              separators=(",", ":")) + "\n").encode("ascii")
        if len(payload) > _MAX_IDENTITY_BYTES * 2 + 4096:
            raise ProgressProtocolError("semantic progress event is oversized")
        view = memoryview(payload)
        while view:
            written = os.write(self.fd, view)
            if written <= 0:
                raise ProgressProtocolError("semantic progress append made no progress")
            view = view[written:]

    def __enter__(self) -> "ChildProgress":
        if self.enabled:
            self._emit({
                "schema": SCHEMA, "nonce": self.nonce, "pid": self.pid,
                "seq": 0, "state": "start", "scope": self.scope,
                "total": self.total,
            })
        return self

    def checkpoint(self, unit: str) -> None:
        if not self.enabled:
            return
        unit = _identity(unit, "child progress unit")
        if unit in self.seen:
            raise ProgressProtocolError(
                f"child repeated progress unit {unit!r}")
        if self.completed >= self.total:
            raise ProgressProtocolError("child exceeded parent finite total")
        self.completed += 1
        self.seq += 1
        self.seen.add(unit)
        self._emit({
            "schema": SCHEMA, "nonce": self.nonce, "pid": self.pid,
            "seq": self.seq, "state": "checkpoint", "scope": self.scope,
            "total": self.total, "completed": self.completed, "unit": unit,
        })

    def __exit__(self, exc_type, _exc, _tb) -> bool:
        try:
            if self.enabled and exc_type is None:
                if self.completed != self.total:
                    raise ProgressProtocolError(
                        "child reached natural return before completing its "
                        f"finite manifest ({self.completed}/{self.total})")
                self.seq += 1
                self._emit({
                    "schema": SCHEMA, "nonce": self.nonce, "pid": self.pid,
                    "seq": self.seq, "state": "terminal", "scope": self.scope,
                    "total": self.total, "completed": self.completed,
                })
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
        return False


def child_progress(scope: str) -> ChildProgress:
    """Return the opt-in direct-child writer for ``scope``."""
    return ChildProgress(scope)
