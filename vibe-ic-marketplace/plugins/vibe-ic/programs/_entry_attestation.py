#!/usr/bin/env python3
"""Runner-owned external entry attestation ledger.

Strict entry provenance cannot come from metadata stored in the run directory:
the author being checked can reconstruct that metadata.  A completed Phase-1
producer therefore appends one row to a fixed, passwd-derived user-state ledger.
The CLI never accepts HOME/XDG/env or a caller-selected ledger path.  Tests may
inject ``ledger_path`` only through the Python API.

Threat boundary: this separates ordinary run-tree authoring from runner-owned
state and defeats hand-written envelopes, public L-doc stamps, stale copies and
same-path replacement.  It is not a cryptographic boundary against malicious
code already executing as the same uid; that requires a separate OS principal
or signing service and is deliberately not claimed here.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

SCHEMA = "vibe-ic-entry-attestation-v1"
_STATE_REL = Path(".local/state/vibe-ic/entry-attestations-v1")
_MAX_LEDGER_BYTES = 16 * 1024 * 1024


class AttestationError(RuntimeError):
    pass


def _canonical_state_dir() -> Path:
    # passwd, not HOME/XDG: a CLI caller cannot redirect strict verification.
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / _STATE_REL


def _project_key(project: Path) -> str:
    return hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()


def ledger_path(project: Path) -> Path:
    return _canonical_state_dir() / f"{_project_key(project)}.jsonl"


def _validate_state_dir(root: Path, *, create: bool) -> None:
    if create and not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        st = root.lstat()
    except OSError as exc:
        raise AttestationError(f"state directory unavailable: {exc}") from exc
    if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
            or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise AttestationError(
            "state directory must be a non-symlink directory owned by the "
            "current uid with mode 0700")


def _open_ledger(path: Path, *, write: bool) -> int:
    _validate_state_dir(path.parent, create=write)
    flags = os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    flags |= (os.O_WRONLY | os.O_APPEND | os.O_CREAT) if write else os.O_RDONLY
    dirfd = -1
    try:
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY
                        | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
        opened_dir = os.fstat(dirfd)
        named_dir = path.parent.lstat()
        if ((opened_dir.st_dev, opened_dir.st_ino)
                != (named_dir.st_dev, named_dir.st_ino)):
            raise AttestationError("state directory inode changed while opening")
        fd = os.open(path.name, flags, 0o600, dir_fd=dirfd)
    except OSError as exc:
        raise AttestationError(f"ledger unavailable: {exc}") from exc
    finally:
        if dirfd >= 0:
            os.close(dirfd)
    st = os.fstat(fd)
    try:
        lst = path.lstat()
    except OSError as exc:
        os.close(fd)
        raise AttestationError(f"ledger identity unavailable: {exc}") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600
            or (st.st_dev, st.st_ino) != (lst.st_dev, lst.st_ino)
            or stat.S_ISLNK(lst.st_mode)):
        os.close(fd)
        raise AttestationError(
            "ledger must be one non-symlink regular file owned by the current "
            "uid with mode 0600 and stable inode")
    return fd


def _file_identity(path: Path, project: Path) -> Dict[str, Any]:
    try:
        rel = path.resolve().relative_to(project.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise AttestationError(f"artifact escapes project: {path}") from exc
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AttestationError(f"artifact unreadable: {rel}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise AttestationError(f"artifact is not a regular file: {rel}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise AttestationError(f"artifact changed while hashing: {rel}")
    return {
        "path": rel,
        "sha256": digest.hexdigest(),
        "stat": {name.removeprefix("st_"): getattr(after, name)
                 for name in fields},
    }


def _artifact_set(project: Path, report: Path,
                  l_doc_dirs: Optional[Iterable[Path]] = None) \
        -> list[Dict[str, Any]]:
    if not report.is_file():
        raise AttestationError("runner completion report is absent")
    dirs = list(l_doc_dirs or [project / "phase1" / "generated_docs"])
    docs = sorted({path for directory in dirs
                   for path in Path(directory).glob("L*.json")})
    if not docs:
        raise AttestationError("runner produced no L-document to attest")
    return [_file_identity(report, project),
            *[_file_identity(path, project) for path in docs if path.is_file()]]


def _load_rows(fd: int) -> list[dict]:
    size = os.fstat(fd).st_size
    if size > _MAX_LEDGER_BYTES:
        raise AttestationError("ledger exceeds bounded parse size")
    os.lseek(fd, 0, os.SEEK_SET)
    raw = b""
    while len(raw) < size:
        raw += os.read(fd, min(1024 * 1024, size - len(raw)))
    rows: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AttestationError(f"malformed ledger row {lineno}") from exc
        if not isinstance(row, dict) or row.get("schema") != SCHEMA:
            raise AttestationError(f"invalid ledger row {lineno}")
        rows.append(row)
    return rows


def record_completed_run(project: Path, *, runner: str, completion_rc: int,
                         report: Path,
                         l_doc_dirs: Optional[Iterable[Path]] = None,
                         ledger_path_override: Optional[Path] = None) -> dict:
    """Append after the runner has written its final report and L-documents."""
    project = project.resolve()
    artifacts = _artifact_set(project, report, l_doc_dirs)
    pst = project.stat()
    row = {
        "schema": SCHEMA,
        "project": str(project),
        "project_stat": {"dev": pst.st_dev, "ino": pst.st_ino},
        "runner": runner,
        "nonce": secrets.token_hex(32),
        "completed_ns": time.time_ns(),
        "completion_rc": int(completion_rc),
        "artifacts": artifacts,
    }
    path = Path(ledger_path_override) if ledger_path_override else ledger_path(project)
    fd = _open_ledger(path, write=True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        payload = (json.dumps(row, sort_keys=True, separators=(",", ":"))
                   + "\n").encode("utf-8")
        if len(payload) > 1024 * 1024:
            raise AttestationError("attestation row is unexpectedly large")
        written = os.write(fd, payload)  # one O_APPEND write: no interleaving
        if written != len(payload):
            raise AttestationError("short ledger append")
        os.fsync(fd)
    finally:
        os.close(fd)
    return row


def verify_latest(project: Path, *,
                  ledger_path_override: Optional[Path] = None) -> Tuple[bool, str]:
    """Strictly verify the latest row and every current artifact identity."""
    project = project.resolve()
    path = Path(ledger_path_override) if ledger_path_override else ledger_path(project)
    try:
        fd = _open_ledger(path, write=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            rows = _load_rows(fd)
        finally:
            os.close(fd)
        if not rows:
            raise AttestationError("external ledger is empty")
        nonces = [row.get("nonce") for row in rows]
        if (any(not isinstance(nonce, str) or len(nonce) != 64 for nonce in nonces)
                or len(set(nonces)) != len(nonces)):
            raise AttestationError("ledger contains an invalid or replayed nonce")
        row = rows[-1]
        if row.get("project") != str(project):
            raise AttestationError("latest row belongs to a different project")
        if row.get("runner") not in {"phase1_one_shot_runner", "gates_atomic"}:
            raise AttestationError("latest row was not committed by an entry producer")
        rc = row.get("completion_rc")
        if not isinstance(rc, int) or isinstance(rc, bool):
            raise AttestationError("latest row has invalid completion rc")
        pst = project.stat()
        if row.get("project_stat") != {"dev": pst.st_dev, "ino": pst.st_ino}:
            raise AttestationError("project identity changed since runner completion")
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) < 2:
            raise AttestationError("latest row lacks report plus L-doc evidence")
        artifact_paths = [item.get("path") for item in artifacts
                          if isinstance(item, dict)]
        if (not artifact_paths or not isinstance(artifact_paths[0], str)
                or not artifact_paths[0].endswith(".json")
                or not any(isinstance(rel, str)
                           and "/generated_docs/L" in f"/{rel}"
                           and rel.endswith(".json")
                           for rel in artifact_paths[1:])):
            raise AttestationError("latest row does not bind a report and L-doc")
        if row.get("runner") == "phase1_one_shot_runner":
            current_doc_dirs = [project / "phase1" / "generated_docs"]
        else:
            current_doc_dirs = [project / "out" / "generated_docs",
                                project / "phase1_proj" / "phase1"
                                / "generated_docs"]
        current_doc_paths = {
            path.resolve().relative_to(project).as_posix()
            for directory in current_doc_dirs if directory.is_dir()
            for path in directory.glob("L*.json") if path.is_file()
        }
        if current_doc_paths != set(artifact_paths[1:]):
            raise AttestationError(
                "current complete L-doc set differs from the attested set")
        current = [_file_identity(project / item.get("path", ""), project)
                   for item in artifacts if isinstance(item, dict)]
        if current != artifacts:
            raise AttestationError("report/L-doc bytes or stat identity changed")
        if len(current) != len(artifacts):
            raise AttestationError("malformed artifact row")
    except (AttestationError, OSError) as exc:
        return False, str(exc)
    return True, "latest external runner attestation exactly matches"
