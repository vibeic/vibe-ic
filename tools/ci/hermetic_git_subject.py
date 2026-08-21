#!/usr/bin/env python3
"""Materialize one object-exact, self-contained Git subject for a hermetic arm.

Ordinary linked worktrees contain a ``.git`` control file whose target is a
host-only path.  Mounting that tree into a container therefore does not mount a
repository at all.  This helper builds a fresh repository with no remotes,
hooks, alternates, user configuration, or checkout filters, copies only the
object closure reachable from the requested commit, and writes tracked blobs
byte-for-byte from the object database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


SCHEMA = 1
KIND = "vibeic.hermetic-git-subject"
MAX_RECORD = 1024 * 1024
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}\Z")


class Refusal(RuntimeError):
    pass


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON number {token!r}")


def _reject_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in out:
            raise ValueError(f"duplicate or non-string JSON key {key!r}")
        out[key] = value
    return out


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _git_env() -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _git(repo: Path, args: Sequence[str], *, stdin: bytes | None = None,
         binary: bool = False) -> str | bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], input=stdin,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env=_git_env(),
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise Refusal(f"git {' '.join(args[:3])} failed: {detail[:500]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "strict").strip()


def _safe_path(raw: bytes) -> PurePosixPath:
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise Refusal("tracked path is not strict UTF-8") from exc
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\0" in value or "\r" in value or "\n" in value):
        raise Refusal(f"tracked path is not canonical: {value!r}")
    return path


def _tree(repo: Path, commit: str
          ) -> tuple[str, str, list[tuple[str, str, PurePosixPath]]]:
    resolved = _git(repo, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
    if not isinstance(resolved, str) or _OID.fullmatch(resolved) is None:
        raise Refusal("commit did not resolve to one full object id")
    tree = _git(repo, ["rev-parse", "--verify", f"{resolved}^{{tree}}"])
    assert isinstance(tree, str)
    raw = _git(repo, ["ls-tree", "-rz", "--full-tree", resolved], binary=True)
    assert isinstance(raw, bytes)
    rows: list[tuple[str, str, PurePosixPath]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, name = record.split(b"\t", 1)
            mode_raw, kind, oid_raw = header.split(b" ", 2)
            mode = mode_raw.decode("ascii", "strict")
            oid = oid_raw.decode("ascii", "strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal("malformed ls-tree record") from exc
        if kind != b"blob" or mode not in {"100644", "100755"}:
            raise Refusal(
                f"hermetic subject contains unsupported tracked mode {mode}")
        if _OID.fullmatch(oid) is None:
            raise Refusal("tracked blob has malformed object id")
        rows.append((mode, oid, _safe_path(name)))
    if rows != sorted(rows, key=lambda row: row[2].as_posix()):
        raise Refusal("Git tree population is not canonically ordered")
    if len({row[2] for row in rows}) != len(rows):
        raise Refusal("Git tree contains duplicate logical paths")
    return resolved, tree, rows


def _write_file(path: Path, raw: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = path.with_name(f".{path.name}.subject.{os.getpid()}")
    fd = os.open(temporary,
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short hermetic-subject write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _copy_object_store(source: Path, destination: Path) -> None:
    common_raw = _git(source, ["rev-parse", "--git-common-dir"])
    assert isinstance(common_raw, str)
    common = Path(common_raw)
    if not common.is_absolute():
        common = source / common
    objects = common.resolve(strict=True) / "objects"
    if not objects.is_dir() or objects.is_symlink():
        raise Refusal("source object store is not a real directory")
    before_paths: list[str] = []
    for current, dirnames, filenames in os.walk(objects, followlinks=False):
        base = Path(current)
        dirnames.sort()
        filenames.sort()
        for name in list(dirnames):
            child = base / name
            if not stat.S_ISDIR(child.lstat().st_mode):
                raise Refusal("source object store contains a special directory")
            rel = child.relative_to(objects)
            destination.joinpath(*rel.parts).mkdir(
                parents=True, exist_ok=True, mode=0o755)
        for name in filenames:
            child = base / name
            rel = child.relative_to(objects)
            if rel.as_posix() == "info/alternates":
                raise Refusal("source object store uses alternates")
            data_before = child.lstat()
            if not stat.S_ISREG(data_before.st_mode) or child.is_symlink():
                raise Refusal("source object store contains a special file")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(child, flags)
            try:
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                held = os.fstat(fd)
            finally:
                os.close(fd)
            data_after = child.lstat()
            identity = lambda row: (
                row.st_dev, row.st_ino, row.st_mode, row.st_size,
                row.st_mtime_ns, row.st_ctime_ns)
            if identity(data_before) != identity(held) \
                    or identity(data_before) != identity(data_after):
                raise Refusal("source object changed while copied")
            _write_file(destination.joinpath(*rel.parts), b"".join(chunks), 0o444)
            before_paths.append(rel.as_posix())
    if not before_paths:
        raise Refusal("source object store is empty")


def _init_repository(output: Path, source: Path, commit: str) -> None:
    template = output.parent / f".{output.name}.empty-template"
    template.mkdir(mode=0o700)
    try:
        object_format = "sha256" if len(commit) == 64 else "sha1"
        proc = subprocess.run(
            ["git", "init", "-q", f"--object-format={object_format}",
             f"--template={template}", str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            env=_git_env(),
        )
    finally:
        template.rmdir()
    if proc.returncode != 0:
        raise Refusal(
            "cannot initialize hermetic repository: "
            + proc.stderr.decode("utf-8", "replace")[:500])
    git_dir = output / ".git"
    config = (
        b"[core]\n"
        + (b"\trepositoryformatversion = 1\n" if object_format == "sha256"
           else b"\trepositoryformatversion = 0\n")
        + b"\tfilemode = true\n"
        b"\tbare = false\n"
        b"\tlogallrefupdates = false\n"
        b"\thooksPath = /dev/null\n"
        b"\tsymlinks = false\n"
        + (b"[extensions]\n\tobjectformat = sha256\n"
           if object_format == "sha256" else b"")
        + b"[gc]\n\tauto = 0\n"
    )
    _write_file(git_dir / "config", config, 0o644)
    _write_file(git_dir / "HEAD", f"{commit}\n".encode("ascii"), 0o644)
    _copy_object_store(source, git_dir / "objects")
    _git(output, ["read-tree", commit])


def _attest(repo: Path, commit: str,
            rows: Sequence[tuple[str, str, PurePosixPath]]) -> dict[str, Any]:
    expected = {path.as_posix(): (mode, oid) for mode, oid, path in rows}
    actual_commit, _tree_oid, actual_rows = _tree(repo, commit)
    if actual_commit != commit or {
            path.as_posix(): (mode, oid) for mode, oid, path in actual_rows
            } != expected:
        raise Refusal("materialized Git object graph differs")
    status = _git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    if status != "":
        raise Refusal("materialized raw-byte worktree is not Git-clean")
    config = _git(repo, ["config", "--local", "--list", "--show-origin"])
    assert isinstance(config, str)
    if ("remote." in config or "url=" in config or "include" in config
            or "alternates" in config):
        raise Refusal("hermetic repository configuration has external authority")
    if (repo / ".git" / "objects" / "info" / "alternates").exists():
        raise Refusal("hermetic repository has object alternates")
    files = []
    total = 0
    for mode, oid, rel in rows:
        raw = _git(repo, ["cat-file", "blob", oid], binary=True)
        assert isinstance(raw, bytes)
        path = repo.joinpath(*rel.parts)
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode)
                or ("100755" if before.st_mode & 0o111 else "100644") != mode):
            raise Refusal(f"tracked path has wrong mode: {rel}")
        observed = path.read_bytes()
        if observed != raw:
            raise Refusal(f"tracked path bytes differ from Git blob: {rel}")
        files.append({"blob_oid": oid, "mode": mode, "path": rel.as_posix(),
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "size": len(raw)})
        total += len(raw)
    return {"commit": commit, "files": files, "total_bytes": total}


def materialize(source: Path, commit: str, output: Path) -> dict[str, Any]:
    source = source.resolve(strict=True)
    if not source.is_dir() or source.is_symlink():
        raise Refusal("object repository is not a directory")
    if output.exists() or output.is_symlink():
        raise Refusal("hermetic subject output already exists")
    resolved, tree, rows = _tree(source, commit)
    output.mkdir(parents=True, mode=0o755)
    _init_repository(output, source, resolved)
    for mode, oid, rel in rows:
        raw = _git(source, ["cat-file", "blob", oid], binary=True)
        assert isinstance(raw, bytes)
        _write_file(output.joinpath(*rel.parts), raw,
                    0o755 if mode == "100755" else 0o644)
    population = _attest(output, resolved, rows)
    payload = {"commit": resolved, "tree": tree, "population": population}
    return {"schema": SCHEMA, "kind": KIND, "complete": True,
            "payload": payload,
            "payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest()}


def _atomic_write(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise Refusal("record output already exists")
    path.parent.resolve(strict=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short subject-record write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record = materialize(args.object_repo, args.commit, args.output)
        _atomic_write(args.record, _canonical(record))
    except (OSError, UnicodeError, ValueError, Refusal) as exc:
        print(f"[NORECORD] hermetic Git subject: {exc}", file=sys.stderr)
        return 2
    print(f"[PASS] hermetic Git subject: {record['payload']['commit'][:12]} ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
