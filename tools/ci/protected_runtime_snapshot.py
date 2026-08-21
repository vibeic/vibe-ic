#!/usr/bin/env python3
"""Materialize the one BASE-authorised runtime used by both landing arms."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_vibeic_{name}", Path(__file__).resolve().with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"trusted sibling {name} is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


transition = _load_sibling("protected_landing_transition")
attester = _load_sibling("trusted_worktree_attest")

SCHEMA = 1
KIND = "vibeic.protected-runtime-snapshot"


class Refusal(RuntimeError):
    pass


def _expected_tree(repo: Path, receipt: Mapping[str, Any]
                   ) -> tuple[dict[PurePosixPath, tuple[str, str]], str,
                              list[dict[str, Any]]]:
    payload = receipt["payload"]
    operation = payload["operation"]
    if operation == "ACTIVATE":
        state_id = payload["candidate_state_id"]
        state_files = payload["candidate_files"]
    elif operation in {"STEADY", "PREPARE"}:
        state_id = payload["base_state_id"]
        state_files = payload["base_files"]
    else:  # parsed receipts already refuse this; retain a local hard boundary.
        raise Refusal("receipt has no executable runtime operation")
    expected = attester._tree(repo, payload["base_commit"])
    for row in state_files:
        path = PurePosixPath(row["path"])
        if path not in expected:
            raise Refusal(f"protected runtime path is absent from BASE: {path}")
        expected[path] = (row["mode"], row["blob_oid"])
    return expected, state_id, list(state_files)


def _write_blob(repo: Path, target: Path, row: Mapping[str, Any]) -> None:
    raw = transition._git(  # type: ignore[attr-defined]
        repo, ["cat-file", "blob", row["blob_oid"]], binary=True)
    assert isinstance(raw, bytes)
    if (len(raw) != row["size"]
            or hashlib.sha256(raw).hexdigest() != row["sha256"]):
        raise Refusal(f"protected blob disagrees with receipt: {row['path']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.runtime.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short protected-blob write")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    os.chmod(temporary, 0o755 if row["mode"] == "100755" else 0o644)
    os.replace(temporary, target)


def _snapshot_payload(receipt: Mapping[str, Any], state_id: str,
                      state_files: list[dict[str, Any]]) -> dict[str, Any]:
    payload = receipt["payload"]
    tuple_payload = {
        "operation": payload["operation"],
        "base_commit": payload["base_commit"],
        "base_tree": payload["base_tree"],
        "candidate_commit": payload["candidate_commit"],
        "candidate_tree": payload["candidate_tree"],
        "transition_id": payload["base_transition_id"],
        "runtime_state_id": state_id,
        "runner": payload["runner"],
        "protected_files": state_files,
    }
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "complete": True,
        "payload": tuple_payload,
        "payload_sha256": hashlib.sha256(
            transition.canonical_bytes(tuple_payload)).hexdigest(),
    }


def validate(*, object_repo: Path, receipt: Mapping[str, Any],
             snapshot: Path) -> dict[str, Any]:
    repo = object_repo.resolve(strict=True)
    expected, state_id, state_files = _expected_tree(repo, receipt)
    try:
        root = snapshot.resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            raise Refusal("runtime snapshot is not a materialized directory")
        attester._attest(root, expected)
    except (OSError, attester.Refusal) as exc:
        raise Refusal(f"runtime raw-byte attestation failed: {exc}") from exc
    return _snapshot_payload(receipt, state_id, state_files)


def materialize(*, object_repo: Path, receipt: Mapping[str, Any],
                base_snapshot: Path, output: Path) -> dict[str, Any]:
    repo = object_repo.resolve(strict=True)
    payload = receipt["payload"]
    try:
        base_root = base_snapshot.resolve(strict=True)
        if not base_root.is_dir() or base_root.is_symlink():
            raise Refusal("BASE snapshot is not a materialized directory")
        expected_base = attester._tree(repo, payload["base_commit"])
        # The trusted verifier deliberately rematerializes BASE with
        # `git archive`, so its post-candidate authority snapshot has no mutable
        # .git control path.  Direct callers may instead provide a registered
        # detached worktree.  Attest either representation exactly; never ask a
        # plain archive for a control file it is intentionally forbidden to
        # carry.
        if (base_root / ".git").exists() or (base_root / ".git").is_symlink():
            attester._attest(
                base_root, expected_base, allow_git_control_file=True,
                object_repo=repo, expected_sha=payload["base_commit"])
        else:
            attester._attest(base_root, expected_base)
    except (OSError, attester.Refusal) as exc:
        raise Refusal(f"BASE snapshot is not object-exact: {exc}") from exc
    if output.exists() or output.is_symlink():
        raise Refusal("runtime output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            base_root, output, symlinks=True,
            ignore=lambda _directory, names: {".git"} if ".git" in names else set())
        # trusted-base-tools is parent-private (0700), while the sealed runtime
        # is consumed through a read-only bind by uid 65534.  Publish only
        # traverse/read permission on the root; no candidate gains host write
        # permission.
        os.chmod(output, 0o755)
        _expected, _state_id, state_files = _expected_tree(repo, receipt)
        for row in state_files:
            _write_blob(repo, output / row["path"], row)
        return validate(object_repo=repo, receipt=receipt, snapshot=output)
    except BaseException:
        # The caller gives this command a fresh, run-private path.  A partial
        # snapshot is never evidence; remove only that exact child on refusal.
        if output.exists() and output.parent != output:
            shutil.rmtree(output, ignore_errors=True)
        raise


def _atomic_write(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise Refusal("runtime record path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short runtime-record write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("materialize")
    check = sub.add_parser("validate")
    for command in (create, check):
        command.add_argument("--object-repo", type=Path, required=True)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--record", type=Path, required=True)
    create.add_argument("--base-snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _algorithm, oid_len = transition._object_format(args.object_repo)
        receipt = transition.strict_load_receipt(args.receipt, oid_len=oid_len)
        if args.command == "materialize":
            record = materialize(
                object_repo=args.object_repo, receipt=receipt,
                base_snapshot=args.base_snapshot, output=args.snapshot)
        else:
            record = validate(
                object_repo=args.object_repo, receipt=receipt,
                snapshot=args.snapshot)
        _atomic_write(args.record, transition.canonical_bytes(record))
    except (OSError, Refusal, transition.Refusal, attester.Refusal) as exc:
        try:
            args.record.unlink()
        except OSError:
            pass
        print(f"[NORECORD] protected runtime snapshot: {exc}", file=sys.stderr)
        return 2
    print(f"[PASS] protected runtime snapshot: "
          f"{record['payload']['runtime_state_id']} "
          f"{record['payload_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
