#!/usr/bin/env python3
"""Measure or validate the exact benchmark-data checkout used by landing.

``measure`` is the network boundary.  It fetches ``origin/main`` into a unique
private ref while holding the repository's landing-checkout flock, proves that
the canonical checkout is already at exactly that fetched commit, removes the
private ref, and only then atomically publishes a complete measurement record.

``validate`` is deliberately fetchless.  It proves that a private worktree's
HEAD and index still equal a caller-supplied measured SHA.  Both modes reject a
dirty (including ignored) tree, sparse/skip-worktree state, replace refs, and an
origin other than the exact canonical repository.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


SCHEMA = 1
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"
CHECKOUT_ENV = "VIBEIC_BENCHMARK_DATA_CHECKOUT"
CANONICAL_ORIGIN = "https://github.com/vibeic/benchmark-data.git"
TEST_OVERRIDE_ENV = "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE"
PRIVATE_REF_PREFIX = "refs/vibeic/landing-checkout-measure"
LOCK_NAME = "vibeic-benchmark-data-landing-checkout.lock"
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class Refusal(RuntimeError):
    """The checkout could not produce complete landing evidence."""


def _git_env() -> dict[str, str]:
    # The path argument, not ambient repository plumbing, names the subject.
    # GIT_NO_REPLACE_OBJECTS is defense in depth; refs/replace are also
    # enumerated and refused so their mere presence remains visible.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return env


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args], env=_git_env(),
            capture_output=True, text=True)
    except OSError as exc:
        raise Refusal(f"git could not be executed: {exc}") from exc


def _git_raw(checkout: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run git without decoding path bytes from its NUL-delimited protocols."""
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args], env=_git_env(),
            capture_output=True)
    except OSError as exc:
        raise Refusal(f"git could not be executed: {exc}") from exc


def _git_visible(checkout: Path, *args: str) -> int:
    """Run a long git operation with diagnostics visible to its owner.

    Byte growth is only an operational liveness signal for the enclosing
    owned-process supervisor.  It never decides freshness or success.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args], env=_git_env()).returncode
    except OSError as exc:
        raise Refusal(f"git could not be executed: {exc}") from exc


def _need(checkout: Path, *args: str, what: str) -> str:
    proc = _git(checkout, *args)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise Refusal(
            f"could not {what} (git rc {proc.returncode})"
            + (f": {detail}" if detail else ""))
    return proc.stdout.strip()


def _expected_origin(test_override: str | None) -> str:
    if test_override is None:
        return CANONICAL_ORIGIN
    if os.environ.get(TEST_OVERRIDE_ENV) != "1":
        raise Refusal(
            "--test-expected-origin is disabled outside the direct-test "
            f"contract ({TEST_OVERRIDE_ENV}=1)")
    return test_override


def _checkout_arg(raw: Path | None) -> Path:
    # The 05:30 contract materializes this exact canonical clone.  An operator
    # may explicitly name the same/another checkout, and the existing corpus
    # pointer remains usable, but an initially-unset environment is not an
    # absent subject: it resolves to the cron-owned canonical path.
    configured = os.environ.get(CHECKOUT_ENV)
    default = (Path(configured) if configured
               else Path.home() / "_matrix_benchmark_data")
    value = raw or (Path(os.environ[CORPUS_ENV])
                    if os.environ.get(CORPUS_ENV) else default)
    try:
        checkout = value.resolve(strict=True)
    except OSError as exc:
        raise Refusal(f"checkout {value} is not readable: {exc}") from exc
    if not checkout.is_dir():
        raise Refusal(f"checkout {checkout} is not a directory")
    return checkout


def _repo_paths(checkout: Path) -> tuple[Path, Path]:
    top_raw = _need(
        checkout, "rev-parse", "--show-toplevel", what="locate checkout root")
    try:
        top = Path(top_raw).resolve(strict=True)
    except OSError as exc:
        raise Refusal(f"git reported an unreadable checkout root: {exc}") from exc
    if top != checkout:
        raise Refusal(
            f"named path {checkout} is not the checkout root (git says {top})")
    bare = _need(
        checkout, "rev-parse", "--is-bare-repository", what="classify checkout")
    if bare != "false":
        raise Refusal(f"{checkout} is not a non-bare worktree")
    common_raw = _need(
        checkout, "rev-parse", "--git-common-dir", what="locate common git dir")
    common = Path(common_raw)
    if not common.is_absolute():
        common = checkout / common
    try:
        common = common.resolve(strict=True)
    except OSError as exc:
        raise Refusal(f"git common directory is unreadable: {exc}") from exc
    return top, common


def _origin(checkout: Path, expected: str) -> str:
    proc = _git(checkout, "remote", "get-url", "--all", "origin")
    urls = proc.stdout.splitlines() if proc.returncode == 0 else []
    if urls != [expected]:
        got = urls if urls else ["<missing or unreadable>"]
        raise Refusal(
            f"origin must be exactly {expected!r}; observed {got!r}")
    return urls[0]


def _config_bool(checkout: Path, key: str) -> bool:
    proc = _git(checkout, "config", "--bool", "--get", key)
    if proc.returncode == 1:
        return False
    if proc.returncode != 0:
        raise Refusal(f"could not read git config {key} (rc {proc.returncode})")
    value = proc.stdout.strip()
    if value not in ("true", "false"):
        raise Refusal(f"git config {key} is not boolean: {value!r}")
    return value == "true"


def _index_flags(checkout: Path) -> None:
    proc = _git(checkout, "ls-files", "-v", "-z")
    if proc.returncode != 0:
        raise Refusal(f"could not inspect index flags (git rc {proc.returncode})")
    skipped: list[str] = []
    assumed: list[str] = []
    for row in proc.stdout.split("\0"):
        if not row:
            continue
        if len(row) < 3 or row[1] != " ":
            raise Refusal("git ls-files returned a malformed index-flag row")
        tag, name = row[0], row[2:]
        if tag == "S":
            skipped.append(name)
        elif tag.islower():
            assumed.append(name)
    if skipped:
        raise Refusal(
            "index carries skip-worktree entries: " + ", ".join(skipped[:5]))
    if assumed:
        raise Refusal(
            "index carries assume-unchanged entries: "
            + ", ".join(assumed[:5]))


def _blob_hasher(oid_len: int, size: int):
    if oid_len == 40:
        digest = hashlib.sha1()
    elif oid_len == 64:
        digest = hashlib.sha256()
    else:
        raise Refusal(f"unsupported git object id length: {oid_len}")
    digest.update(f"blob {size}\0".encode("ascii"))
    return digest


def _stable_regular_blob(path: Path, oid_len: int, expected_mode: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise Refusal(f"tracked regular file is unreadable: {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Refusal(f"tracked regular file changed type: {path}")
        executable = bool(before.st_mode & 0o111)
        if executable != (expected_mode == "100755"):
            raise Refusal(
                f"tracked executable mode differs from the index: {path}")
        digest = _blob_hasher(oid_len, before.st_size)
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    stable = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable or total != before.st_size:
        raise Refusal(f"tracked file changed while its bytes were attested: {path}")
    try:
        current = path.lstat()
    except OSError as exc:
        raise Refusal(f"tracked file disappeared after attestation: {path}: {exc}") from exc
    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise Refusal(f"tracked file was replaced during attestation: {path}")
    return digest.hexdigest()


def _stable_symlink_blob(path: Path, oid_len: int) -> str:
    try:
        before = path.lstat()
        if not stat.S_ISLNK(before.st_mode):
            raise Refusal(f"tracked symlink changed type: {path}")
        target = os.fsencode(os.readlink(path))
        after = path.lstat()
    except OSError as exc:
        raise Refusal(f"tracked symlink is unreadable: {path}: {exc}") from exc
    if (before.st_dev, before.st_ino, before.st_mtime_ns,
            before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_mtime_ns,
            after.st_ctime_ns):
        raise Refusal(f"tracked symlink changed while being attested: {path}")
    digest = _blob_hasher(oid_len, len(target))
    digest.update(target)
    return digest.hexdigest()


def _tracked_bytes_equal_index(checkout: Path) -> None:
    """Prove every tracked worktree byte is the blob named by the index.

    Porcelain cleanliness is filter-aware: a malicious or merely local smudge
    filter can make the bytes a gate reads differ from HEAD while ``status``
    remains empty.  This census hashes raw regular-file bytes and symlink target
    bytes as Git blobs, without invoking clean/smudge filters.
    """
    proc = _git_raw(checkout, "ls-files", "--stage", "-z")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
        raise Refusal("could not enumerate indexed blobs"
                      + (f": {detail}" if detail else ""))
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, raw_name = raw.split(b"\t", 1)
            raw_mode, raw_oid, raw_stage = meta.split()
            mode = raw_mode.decode("ascii")
            oid = raw_oid.decode("ascii")
            stage = raw_stage.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal("git returned a malformed indexed-blob row") from exc
        if stage != "0" or not OID_RE.fullmatch(oid):
            raise Refusal(
                f"index entry is not a stage-0 full blob id: "
                f"{os.fsdecode(raw_name)!r}")
        rel = Path(os.fsdecode(raw_name))
        if rel.is_absolute() or ".." in rel.parts:
            raise Refusal(f"index returned an unsafe tracked path: {rel!s}")
        path = checkout / rel
        if mode in ("100644", "100755"):
            actual = _stable_regular_blob(path, len(oid), mode)
        elif mode == "120000":
            actual = _stable_symlink_blob(path, len(oid))
        else:
            raise Refusal(
                f"unsupported tracked entry mode {mode} for {rel!s}")
        if actual != oid:
            raise Refusal(
                f"raw tracked bytes differ from indexed blob for {rel!s}: "
                f"index {oid}, worktree {actual}")


def _inspect(checkout: Path, expected_origin: str) -> tuple[str, Path]:
    _, common = _repo_paths(checkout)
    origin = _origin(checkout, expected_origin)
    if (_config_bool(checkout, "core.sparseCheckout")
            or _config_bool(checkout, "core.sparseCheckoutCone")):
        raise Refusal("sparse checkout is enabled")
    _index_flags(checkout)

    replacements = _need(
        checkout, "for-each-ref", "--format=%(refname)", "refs/replace/",
        what="enumerate replace refs")
    if replacements:
        raise Refusal(
            "replace refs can redefine checkout objects: "
            + ", ".join(replacements.splitlines()[:5]))

    status = _git(
        checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all",
        "--ignored=matching", "--ignore-submodules=none")
    if status.returncode != 0:
        raise Refusal(f"could not inspect checkout cleanliness (rc {status.returncode})")
    if status.stdout:
        first = status.stdout.split("\0", 1)[0]
        raise Refusal(
            "checkout is dirty, including untracked/ignored files; first "
            f"entry: {first!r}")

    cached = _git(
        checkout, "diff", "--cached", "--quiet", "--no-ext-diff", "HEAD", "--")
    if cached.returncode == 1:
        raise Refusal("checkout index differs from HEAD")
    if cached.returncode != 0:
        raise Refusal(f"could not compare checkout index to HEAD (rc {cached.returncode})")
    _tracked_bytes_equal_index(checkout)
    return origin, common


def _head(checkout: Path) -> str:
    sha = _need(
        checkout, "rev-parse", "--verify", "HEAD^{commit}", what="resolve HEAD")
    if not OID_RE.fullmatch(sha):
        raise Refusal(f"HEAD did not resolve to a full object id: {sha!r}")
    return sha


@contextmanager
def _fetch_lock(common: Path) -> Iterator[None]:
    lock_path = common / LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise Refusal(f"could not open checkout flock {lock_path}: {exc}") from exc
    try:
        # Queueing is not evidence.  Another measurement owns the checkout, so
        # this invocation reports BUSY/NORECORD immediately and a scheduler may
        # retry it as a new run; elapsed waiting never becomes a verdict.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise Refusal(
            "checkout measurement lock is BUSY; retry as a new run") from exc
    except OSError as exc:
        raise Refusal(f"checkout flock failed: {exc}") from exc
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _delete_private_ref(checkout: Path, ref: str) -> None:
    deleted = _git(checkout, "update-ref", "-d", ref)
    if deleted.returncode != 0:
        raise Refusal(
            f"could not delete private fetch ref {ref} (rc {deleted.returncode})")
    remains = _git(checkout, "show-ref", "--verify", "--quiet", ref)
    if remains.returncode == 0:
        raise Refusal(f"private fetch ref {ref} remained after deletion")
    if remains.returncode != 1:
        raise Refusal(f"could not verify deletion of private fetch ref {ref}")


def _delete_stale_private_refs(checkout: Path) -> None:
    """Sweep interrupted prior measurements while holding the shared flock."""
    refs = _need(
        checkout, "for-each-ref", "--format=%(refname)",
        PRIVATE_REF_PREFIX + "/", what="enumerate private measurement refs")
    for ref in refs.splitlines():
        if ref:
            _delete_private_ref(checkout, ref)


def _measure(checkout: Path, expected_origin: str) -> tuple[str, str]:
    origin, common = _inspect(checkout, expected_origin)
    ref = f"{PRIVATE_REF_PREFIX}/{os.getpid()}-{uuid.uuid4().hex}"
    problem: Refusal | None = None
    fetched = ""
    with _fetch_lock(common):
        try:
            _delete_stale_private_refs(checkout)
            # `--progress` is inherited by the parent-owned supervisor.  There
            # is no total elapsed cutoff: only natural exit plus the immutable
            # ref/object/HEAD checks below decide this measurement.
            fetch_rc = _git_visible(
                checkout, "fetch", "--progress", "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules", "--force", "origin",
                f"+refs/heads/main:{ref}")
            if fetch_rc != 0:
                raise Refusal(
                    f"fresh origin/main fetch failed (rc {fetch_rc})")
            fetched = _need(
                checkout, "rev-parse", "--verify", f"{ref}^{{commit}}",
                what="resolve freshly fetched origin/main")
            if not OID_RE.fullmatch(fetched):
                raise Refusal(
                    f"fresh origin/main did not resolve to a full object id: {fetched!r}")
            head = _head(checkout)
            if head != fetched:
                raise Refusal(
                    f"canonical checkout is stale: HEAD {head} != freshly "
                    f"fetched origin/main {fetched}")
            # Reinspect after the network operation.  A clean tree observed
            # before fetch is not evidence that it stayed clean during fetch.
            _inspect(checkout, expected_origin)
        except Refusal as exc:
            problem = exc
        finally:
            try:
                _delete_private_ref(checkout, ref)
            except Refusal as exc:
                problem = exc if problem is None else Refusal(f"{problem}; {exc}")
    if problem is not None:
        raise problem
    # The private ref is gone; prove the checkout/index/origin once more before
    # publishing the record that later validation trusts.
    origin, _ = _inspect(checkout, expected_origin)
    if _head(checkout) != fetched:
        raise Refusal("checkout HEAD moved after the fresh measurement")
    return fetched, origin


def _validate(checkout: Path, expected_origin: str, expected_sha: str) -> str:
    if not OID_RE.fullmatch(expected_sha):
        raise Refusal("--expected-sha must be a full lowercase git object id")
    head = _head(checkout)
    if head != expected_sha:
        raise Refusal(
            f"private worktree HEAD {head} != expected measured SHA {expected_sha}")
    # Read HEAD on both sides of the complete raw-byte census.  A checkout that
    # moves during validation has no single tree identity and therefore no
    # record, even if it happens to move back later.
    _inspect(checkout, expected_origin)
    if _head(checkout) != head:
        raise Refusal("private worktree HEAD moved during validation")
    return head


def _prepare_record(record: Path, checkout: Path) -> Path:
    resolved = record.resolve()
    try:
        resolved.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise Refusal("measurement record must live outside the measured checkout")
    if resolved.exists() and resolved.is_dir():
        raise Refusal(f"measurement record path is a directory: {resolved}")
    try:
        resolved.unlink(missing_ok=True)
    except OSError as exc:
        raise Refusal(f"could not clear prior measurement record: {exc}") from exc
    return resolved


def _write_record(path: Path, doc: dict[str, object]) -> None:
    payload = (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
               + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    fd = -1
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fd = -1
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except OSError:
            pass
        raise Refusal(f"could not atomically publish measurement record: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("measure", "validate"):
        mode = sub.add_parser(name)
        mode.add_argument("--checkout", type=Path)
        mode.add_argument("--test-expected-origin", help=argparse.SUPPRESS)
        if name == "measure":
            mode.add_argument("--record", type=Path, required=True)
        else:
            mode.add_argument("--expected-sha", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Bind the requested final path before inspecting the checkout.  Even an
    # unreadable/missing checkout must not leave yesterday's complete-looking
    # measurement where today's caller expects a fresh one.
    record: Path | None = (args.record.resolve()
                           if args.mode == "measure" else None)
    previous_handlers: dict[int, object] = {}

    def _signal_refusal(signum, _frame):
        raise Refusal(f"interrupted by signal {signum}; no measurement exists")

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous_handlers[signum] = signal.signal(signum, _signal_refusal)
    try:
        checkout = _checkout_arg(args.checkout)
        expected_origin = _expected_origin(args.test_expected_origin)
        if args.mode == "measure":
            assert record is not None
            record = _prepare_record(record, checkout)
            sha, origin = _measure(checkout, expected_origin)
            doc = {
                "schema": SCHEMA,
                "complete": True,
                "sha": sha,
                "origin": origin,
                "path": str(checkout),
            }
            _write_record(record, doc)
            print(f"[PASS] benchmark-data checkout measured at {sha}")
        else:
            sha = _validate(checkout, expected_origin, args.expected_sha)
            print(f"[PASS] benchmark-data private worktree validated at {sha}")
        return 0
    except Refusal as exc:
        if record is not None:
            try:
                record.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"[NORECORD] benchmark-data landing checkout: {exc}", file=sys.stderr)
        return 2
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
