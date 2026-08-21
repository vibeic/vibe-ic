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


def _git_env() -> dict[str, str]:
    """A Git query may not inherit caller-selected refs/config namespaces."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update({
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    return env


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], env=_git_env(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise Refusal(f"git {' '.join(args[:2])} failed: {detail[:240]}")
    return proc.stdout


def _blob_digest(data: bytes, oid_len: int) -> str:
    digest = hashlib.sha1() if oid_len == 40 else hashlib.sha256()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _tree(repo: Path, sha: str) -> dict[PurePosixPath, tuple[str, str]]:
    raw_tree = _git(repo, "ls-tree", "-rz", "--full-tree", sha)
    rows: dict[PurePosixPath, tuple[str, str]] = {}
    for raw in raw_tree.split(b"\0"):
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


def _ascii_line(raw: bytes, what: str) -> str:
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise Refusal(f"{what} is not ASCII") from exc
    if not value or "\n" in value or "\r" in value:
        raise Refusal(f"{what} is not one canonical line")
    return value


def _resolve_git_path(base: Path, value: str, what: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise Refusal(f"{what} cannot be resolved: {exc}") from exc
    return resolved


def _parse_stage_zero_index(raw: bytes
                            ) -> dict[PurePosixPath, tuple[str, str]]:
    rows: dict[PurePosixPath, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, raw_path = record.split(b"\t", 1)
            raw_mode, raw_oid, raw_stage = meta.split()
            mode = raw_mode.decode("ascii", errors="strict")
            oid = raw_oid.decode("ascii", errors="strict")
            stage = raw_stage.decode("ascii", errors="strict")
            rel = PurePosixPath(os.fsdecode(raw_path))
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal("linked-worktree index has a malformed row") from exc
        if (stage != "0" or mode not in {"100644", "100755", "120000"}
                or len(oid) not in {40, 64}
                or any(ch not in "0123456789abcdef" for ch in oid)
                or rel.is_absolute() or ".." in rel.parts or rel in rows):
            raise Refusal(f"linked-worktree index has an unsafe row: {rel!s}")
        rows[rel] = (mode, oid)
    return rows


def _attest_linked_worktree_control(
        snapshot: Path, object_repo: Path, expected_sha: str,
        expected: dict[PurePosixPath, tuple[str, str]]) -> None:
    """Bind the checkout's control file and index, not only visible bytes.

    A clean/smudge filter, sparse index, alternate gitdir, or staged replacement
    must not be able to make later gates consume a different population after
    raw worktree bytes were attested.
    """
    control = snapshot / ".git"
    try:
        before = control.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise Refusal("worktree .git control path is not a single-link file")
        raw = control.read_bytes()
        after = control.lstat()
    except OSError as exc:
        raise Refusal(f"cannot read worktree .git control file: {exc}") from exc
    if (len(raw) > 4096
            or (before.st_dev, before.st_ino, before.st_mode,
                before.st_nlink, before.st_size, before.st_mtime_ns,
                before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mode,
                after.st_nlink, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns)):
        raise Refusal("worktree .git control file changed while read")
    line = _ascii_line(raw, "worktree .git control file")
    if not line.startswith("gitdir: "):
        raise Refusal("worktree .git control file has no canonical gitdir")
    gitdir = _resolve_git_path(snapshot, line[8:], "worktree gitdir")
    if gitdir.is_symlink() or not gitdir.is_dir():
        raise Refusal("worktree gitdir is not a materialized directory")

    common_raw = _ascii_line(
        _git(object_repo, "rev-parse", "--git-common-dir"),
        "object repository common dir")
    common = _resolve_git_path(object_repo, common_raw,
                               "object repository common dir")
    try:
        relative_gitdir = gitdir.relative_to(common / "worktrees")
    except ValueError as exc:
        raise Refusal("worktree gitdir is outside the object repository") from exc
    if not relative_gitdir.parts:
        raise Refusal("worktree gitdir has no registered worktree identity")

    observed_gitdir = _resolve_git_path(
        snapshot,
        _ascii_line(_git(snapshot, "rev-parse", "--git-dir"),
                    "worktree gitdir query"),
        "queried worktree gitdir")
    observed_common = _resolve_git_path(
        snapshot,
        _ascii_line(_git(snapshot, "rev-parse", "--git-common-dir"),
                    "worktree common-dir query"),
        "queried worktree common dir")
    if observed_gitdir != gitdir or observed_common != common:
        raise Refusal("worktree control metadata resolves to another repository")
    head = _ascii_line(_git(snapshot, "rev-parse", "HEAD^{commit}"),
                       "worktree HEAD")
    if head != expected_sha:
        raise Refusal("worktree HEAD does not equal the expected commit")

    index = gitdir / "index"
    try:
        index_stat = index.lstat()
    except OSError as exc:
        raise Refusal(f"worktree index is absent: {exc}") from exc
    if (not stat.S_ISREG(index_stat.st_mode) or index_stat.st_nlink != 1
            or index.is_symlink()):
        raise Refusal("worktree index is not a private regular file")
    indexed = _parse_stage_zero_index(
        _git(snapshot, "ls-files", "--stage", "-z", "--full-name"))
    if indexed != expected:
        raise Refusal("worktree stage-0 index differs from the expected tree")
    flags = _git(snapshot, "ls-files", "-v", "-z", "--full-name")
    flag_rows = [record for record in flags.split(b"\0") if record]
    try:
        flagged_paths = {
            PurePosixPath(os.fsdecode(record[2:]))
            for record in flag_rows if len(record) >= 3 and record[:2] == b"H "
        }
    except (ValueError, UnicodeDecodeError) as exc:
        raise Refusal("worktree index flags are malformed") from exc
    if len(flag_rows) != len(flagged_paths) or flagged_paths != set(expected):
        raise Refusal("worktree index carries skip/assume/unmerged flags")
    if _git(object_repo, "for-each-ref", "--format=%(refname)",
            "refs/replace").strip():
        raise Refusal("object repository carries replacement refs")
    alternates = common / "objects" / "info" / "alternates"
    if alternates.exists():
        raise Refusal("object repository carries an alternates file")


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
            *, allow_git_control_file: bool = False,
            object_repo: Path | None = None,
            expected_sha: str | None = None) -> None:
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
    if allow_git_control_file:
        if object_repo is None or expected_sha is None:
            raise Refusal("linked-worktree control attestation lacks object identity")
        _attest_linked_worktree_control(
            snapshot, object_repo, expected_sha, expected)


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
            object_repo=repo,
            expected_sha=args.expected_sha,
        )
    except (OSError, Refusal, subprocess.SubprocessError) as exc:
        print(f"[NORECORD] trusted tool snapshot: {exc}", file=sys.stderr)
        return 2
    print(f"[PASS] trusted tool snapshot raw-attested at {args.expected_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
