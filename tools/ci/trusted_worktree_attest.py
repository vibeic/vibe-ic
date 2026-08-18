#!/usr/bin/env python3
"""Byte-attest an object-exact plain snapshot against one Git commit."""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


class Refusal(RuntimeError):
    pass


def _blob_digest(data: bytes, oid_len: int) -> str:
    digest = hashlib.sha1() if oid_len == 40 else hashlib.sha256()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _tree(repo: Path, sha: str) -> dict[PurePosixPath, tuple[str, str]]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C"})
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-rz", "--full-tree", sha],
        env=env, capture_output=True)
    if proc.returncode != 0:
        raise Refusal("cannot enumerate the expected commit tree")
    rows: dict[PurePosixPath, tuple[str, str]] = {}
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, raw_path = raw.split(b"\t", 1)
            raw_mode, raw_type, raw_oid = meta.split()
            mode, kind, oid = (raw_mode.decode("ascii"),
                               raw_type.decode("ascii"),
                               raw_oid.decode("ascii"))
            rel = PurePosixPath(os.fsdecode(raw_path))
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal("malformed ls-tree record") from exc
        if (kind != "blob" or mode not in {"100644", "100755", "120000"}
                or len(oid) not in {40, 64}
                or any(ch not in "0123456789abcdef" for ch in oid)
                or rel.is_absolute() or ".." in rel.parts or rel in rows):
            raise Refusal(f"unsupported/unsafe tree entry: {rel!s}")
        rows[rel] = (mode, oid)
    if not rows:
        raise Refusal("expected commit tree has no regular/symlink entries")
    return rows


def _snapshot_entries(root: Path, *, allow_git_control_file: bool = False
                      ) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    files: set[PurePosixPath] = set()
    dirs: set[PurePosixPath] = set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        for name in list(dirnames):
            path = base / name
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if path.is_symlink():
                files.add(rel)
                dirnames.remove(name)
            else:
                dirs.add(rel)
        for name in filenames:
            rel = PurePosixPath((base / name).relative_to(root).as_posix())
            if allow_git_control_file and rel == PurePosixPath(".git"):
                path = base / name
                if path.is_symlink() or not path.is_file():
                    raise Refusal("worktree .git control path is not a regular file")
                continue
            files.add(rel)
    return files, dirs


def _attest(snapshot: Path, expected: dict[PurePosixPath, tuple[str, str]],
            *, allow_git_control_file: bool = False) -> None:
    observed_files, observed_dirs = _snapshot_entries(
        snapshot, allow_git_control_file=allow_git_control_file)
    expected_files = set(expected)
    expected_dirs = {PurePosixPath(*rel.parts[:i]) for rel in expected_files
                     for i in range(1, len(rel.parts))}
    if observed_files != expected_files:
        extra = sorted(str(p) for p in observed_files - expected_files)
        missing = sorted(str(p) for p in expected_files - observed_files)
        raise Refusal(f"snapshot path set differs; extra={extra[:3]!r}, "
                      f"missing={missing[:3]!r}")
    if observed_dirs != expected_dirs:
        raise Refusal("snapshot directory set differs from the commit tree")
    for rel in sorted(expected_files, key=str):
        mode, oid = expected[rel]
        path = snapshot.joinpath(*rel.parts)
        before = path.lstat()
        if mode == "120000":
            if not stat.S_ISLNK(before.st_mode):
                raise Refusal(f"tracked symlink changed type: {rel}")
            data = os.fsencode(os.readlink(path))
        else:
            if not stat.S_ISREG(before.st_mode):
                raise Refusal(f"tracked file changed type: {rel}")
            if bool(before.st_mode & 0o111) != (mode == "100755"):
                raise Refusal(f"tracked executable mode differs: {rel}")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags)
            try:
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
                after_fd = os.fstat(fd)
            finally:
                os.close(fd)
            if ((before.st_dev, before.st_ino, before.st_size,
                 before.st_mtime_ns, before.st_ctime_ns) !=
                    (after_fd.st_dev, after_fd.st_ino, after_fd.st_size,
                     after_fd.st_mtime_ns, after_fd.st_ctime_ns)):
                raise Refusal(f"tracked file changed while read: {rel}")
        after = path.lstat()
        if ((before.st_dev, before.st_ino, before.st_mtime_ns,
             before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_mtime_ns,
                 after.st_ctime_ns)):
            raise Refusal(f"tracked entry changed while attested: {rel}")
        if _blob_digest(data, len(oid)) != oid:
            raise Refusal(f"raw bytes differ from expected blob: {rel}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--object-repo", type=Path, required=True)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--expected-sha", required=True)
    ap.add_argument(
        "--allow-git-control-file", action="store_true",
        help="ignore the regular root .git control file of a linked worktree",
    )
    args = ap.parse_args(argv)
    try:
        snapshot = args.snapshot.resolve(strict=True)
        repo = args.object_repo.resolve(strict=True)
        if not snapshot.is_dir():
            raise Refusal("snapshot is not a directory")
        _attest(
            snapshot,
            _tree(repo, args.expected_sha),
            allow_git_control_file=args.allow_git_control_file,
        )
    except (OSError, Refusal, subprocess.SubprocessError) as exc:
        print(f"[NORECORD] trusted tool snapshot: {exc}", file=sys.stderr)
        return 2
    print(f"[PASS] trusted tool snapshot raw-attested at {args.expected_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
