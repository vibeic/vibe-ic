#!/usr/bin/env python3
"""Bind and publish parent-owned evidence from one hermetic landing arm.

This is a BLOCKING validator.  A refusal produces no validation record and is
never interpreted as a test or landing verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = 1
KIND = "vibeic.hermetic-landing-arm-validation"
ARMS = frozenset({"A1", "B1", "A2", "B2"})
LANDING_ARMS = frozenset({"A2", "B2"})
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class Refusal(RuntimeError):
    """The arm evidence cannot be bound without ambiguity."""


def _reject_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise Refusal(f"duplicate or non-string JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise Refusal(f"non-finite JSON number {value!r}")


def strict_loads(raw: bytes | str, *, what: str) -> Any:
    if isinstance(raw, bytes):
        if len(raw) > MAX_JSON_BYTES:
            raise Refusal(f"{what} exceeds {MAX_JSON_BYTES} bytes")
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise Refusal(f"{what} is not strict UTF-8") from exc
    else:
        text = raw
        if len(text.encode("utf-8", "strict")) > MAX_JSON_BYTES:
            raise Refusal(f"{what} exceeds {MAX_JSON_BYTES} bytes")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Refusal(f"{what} is not strict JSON: {exc}") from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise Refusal(f"record is not canonically serialisable: {exc}") from exc


def canonical_bytes(value: Any) -> bytes:
    return _canonical(value) + b"\n"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_keys(value: Any, keys: Iterable[str], what: str) -> Mapping[str, Any]:
    expected = set(keys)
    if not isinstance(value, dict) or set(value) != expected:
        got = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise Refusal(f"{what} has the wrong schema: {got!r}")
    return value


def _sha(value: Any, what: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise Refusal(f"{what} is not a lowercase SHA-256 digest")
    return value


def _oid(value: Any, what: str) -> str:
    if not isinstance(value, str) or OID_RE.fullmatch(value) is None:
        raise Refusal(f"{what} is not a full lowercase object id")
    return value


def _nonnegative_int(value: Any, what: str) -> int:
    if type(value) is not int or value < 0:
        raise Refusal(f"{what} is not a nonnegative integer")
    return value


def _safe_rel(value: Any, what: str) -> str:
    if (not isinstance(value, str) or not value or "\0" in value
            or "\r" in value or "\n" in value):
        raise Refusal(f"{what} is not a bounded relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise Refusal(f"{what} is not a canonical relative path")
    return value


def _absolute_path(value: Any, what: str) -> str:
    if (not isinstance(value, str) or not value or "\0" in value
            or "\r" in value or "\n" in value):
        raise Refusal(f"{what} is not one absolute path")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise Refusal(f"{what} is not one canonical absolute path")
    return value


def _command(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 1:
        raise Refusal("validated command is not one direct executable")
    command = value[0]
    if not isinstance(command, str):
        raise Refusal("validated command is not a string")
    path = PurePosixPath(command)
    try:
        relative = path.relative_to("/subject")
    except ValueError as exc:
        raise Refusal("validated command is outside /subject") from exc
    if (command == "/subject" or path.as_posix() != command
            or any(part in {"", ".", ".."} for part in relative.parts)):
        raise Refusal("validated command is not canonical /subject/REL")
    return [command]


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_regular(path: Path, what: str, *, limit: int = MAX_FILE_BYTES
                  ) -> tuple[bytes, os.stat_result]:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or path.is_symlink()
                or before.st_nlink != 1):
            raise Refusal(f"{what} is not a single-link regular file")
        if before.st_size > limit:
            raise Refusal(f"{what} exceeds {limit} bytes")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise Refusal(f"{what} exceeds {limit} bytes")
                chunks.append(chunk)
            held = os.fstat(fd)
        finally:
            os.close(fd)
        after = path.lstat()
    except OSError as exc:
        raise Refusal(f"cannot read {what}: {exc}") from exc
    if (_identity(before) != _identity(held)
            or _identity(before) != _identity(after)):
        raise Refusal(f"{what} changed while read")
    return b"".join(chunks), before


def _file_binding(path: Path, what: str, *, limit: int = MAX_FILE_BYTES
                  ) -> tuple[dict[str, Any], bytes]:
    raw, _info = _read_regular(path, what, limit=limit)
    return {"sha256": _sha256(raw), "size": len(raw)}, raw


def _resolved_directory(path: Path, what: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        info = resolved.lstat()
    except OSError as exc:
        raise Refusal(f"cannot resolve {what}: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or resolved.is_symlink():
        raise Refusal(f"{what} is not a directory")
    return resolved


def _resolved_file(path: Path, what: str) -> Path:
    try:
        supplied = Path(os.path.abspath(path))
        supplied_info = supplied.lstat()
        if (not stat.S_ISREG(supplied_info.st_mode) or supplied.is_symlink()):
            raise Refusal(f"{what} is not a direct regular file")
        resolved = supplied.resolve(strict=True)
        info = resolved.lstat()
    except OSError as exc:
        raise Refusal(f"cannot resolve {what}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or resolved.is_symlink():
        raise Refusal(f"{what} is not a regular file")
    return resolved


def _load_exact_module(path: Path, role: str) -> tuple[ModuleType, Path,
                                                        dict[str, Any]]:
    resolved = _resolved_file(path, role)
    binding, before_raw = _file_binding(
        resolved, role, limit=MAX_JSON_BYTES * 4)
    name = f"_vibeic_{role.replace(' ', '_')}_{binding['sha256']}"
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise Refusal(f"cannot load exact {role}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise Refusal(f"cannot execute exact {role}: {exc}") from exc
    finally:
        sys.dont_write_bytecode = prior
    after_binding, after_raw = _file_binding(
        resolved, role, limit=MAX_JSON_BYTES * 4)
    if binding != after_binding or before_raw != after_raw:
        raise Refusal(f"{role} changed while loaded")
    return module, resolved, {"path": str(resolved), **binding}


def _digest_record(value: Any, what: str, *, path: bool = False
                   ) -> dict[str, Any]:
    keys = {"sha256", "size", "path"} if path else {"sha256", "size"}
    row = _exact_keys(value, keys, what)
    result = {
        "sha256": _sha(row["sha256"], f"{what}.sha256"),
        "size": _nonnegative_int(row["size"], f"{what}.size"),
    }
    if path:
        result = {"path": _absolute_path(row["path"], f"{what}.path"), **result}
    return result


def _tree_record(value: Any, what: str) -> dict[str, Any]:
    row = _exact_keys(
        value, {"digest", "directories", "files", "total_bytes"}, what)
    return {
        "digest": _sha(row["digest"], f"{what}.digest"),
        "directories": _nonnegative_int(
            row["directories"], f"{what}.directories"),
        "files": _nonnegative_int(row["files"], f"{what}.files"),
        "total_bytes": _nonnegative_int(
            row["total_bytes"], f"{what}.total_bytes"),
    }


def _input_file_record(value: Any, what: str) -> dict[str, Any]:
    row = _exact_keys(
        value, {"mode", "permissions", "sha256", "size"}, what)
    if row["mode"] not in {"100644", "100755"}:
        raise Refusal(f"{what}.mode is not regular")
    permissions = row["permissions"]
    if (not isinstance(permissions, str)
            or re.fullmatch(r"0[0-7]{3}", permissions) is None):
        raise Refusal(f"{what}.permissions is malformed")
    return {
        "mode": row["mode"],
        "permissions": permissions,
        "sha256": _sha(row["sha256"], f"{what}.sha256"),
        "size": _nonnegative_int(row["size"], f"{what}.size"),
    }


def _inputs_record(value: Any) -> dict[str, Any]:
    inputs = _exact_keys(value, {
        "corpus", "overlays", "progress_plan", "runtime",
        "runtime_progress_plan", "selection", "subject",
    }, "validation inputs")
    overlays = inputs["overlays"]
    if not isinstance(overlays, list) or not overlays:
        raise Refusal("validation overlays are not a non-empty list")
    parsed_overlays: list[dict[str, Any]] = []
    observed_paths: list[str] = []
    for index, value_row in enumerate(overlays):
        row = _exact_keys(
            value_row, {"destination", "path", "source_file"},
            f"validation overlay[{index}]")
        rel = _safe_rel(row["path"], f"validation overlay[{index}].path")
        if row["destination"] != f"/subject/{rel}":
            raise Refusal("validation overlay destination differs")
        parsed_overlays.append({
            "destination": row["destination"],
            "path": rel,
            "source_file": _input_file_record(
                row["source_file"], f"validation overlay[{index}].source_file"),
        })
        observed_paths.append(rel)
    if observed_paths != sorted(set(observed_paths)):
        raise Refusal("validation overlays are not sorted and unique")
    return {
        "corpus": _tree_record(inputs["corpus"], "validation corpus"),
        "overlays": parsed_overlays,
        "progress_plan": _digest_record(
            inputs["progress_plan"], "validation progress plan"),
        "runtime": _tree_record(inputs["runtime"], "validation runtime"),
        "runtime_progress_plan": _digest_record(
            inputs["runtime_progress_plan"], "validation runtime progress plan"),
        "selection": _input_file_record(
            inputs["selection"], "validation selection"),
        "subject": _tree_record(inputs["subject"], "validation subject"),
    }


def _artifact_manifest(value: Any) -> dict[str, Any]:
    manifest = _exact_keys(
        value, {"files", "total_bytes", "tree_sha256"},
        "validation artifact manifest")
    if not isinstance(manifest["files"], list):
        raise Refusal("validation artifact rows are not a list")
    files: list[dict[str, Any]] = []
    paths: list[str] = []
    total = 0
    for index, value_row in enumerate(manifest["files"]):
        row = _exact_keys(
            value_row, {"mode", "path", "sha256", "size"},
            f"validation artifact[{index}]")
        if row["mode"] not in {"100644", "100755"}:
            raise Refusal("validation artifact mode is not regular")
        rel = _safe_rel(row["path"], f"validation artifact[{index}].path")
        size = _nonnegative_int(row["size"], f"validation artifact[{index}].size")
        files.append({
            "mode": row["mode"],
            "path": rel,
            "sha256": _sha(row["sha256"], f"validation artifact[{index}].sha256"),
            "size": size,
        })
        paths.append(rel)
        total += size
    if paths != sorted(set(paths)):
        raise Refusal("validation artifact paths are not sorted and unique")
    if total != _nonnegative_int(
            manifest["total_bytes"], "validation artifact total"):
        raise Refusal("validation artifact byte total differs")
    expected_tree = _sha256(_canonical({"files": files, "schema": SCHEMA}))
    tree = _sha(manifest["tree_sha256"], "validation artifact tree")
    if tree != expected_tree:
        raise Refusal("validation artifact tree digest differs")
    return {"files": files, "total_bytes": total, "tree_sha256": tree}


def _completion_record(value: Any, artifacts: Mapping[str, dict[str, Any]],
                       arm: str) -> dict[str, Any] | None:
    if value is None:
        if arm in LANDING_ARMS:
            raise Refusal("landing validation has no completion binding")
        return None
    if arm not in LANDING_ARMS:
        raise Refusal("pytest validation unexpectedly has a completion binding")
    row = _exact_keys(value, {
        "base", "head", "hygiene", "path", "payload_sha256", "sha256", "size",
    }, "validation completion")
    path = _safe_rel(row["path"], "validation completion path")
    parsed = {
        "base": _oid(row["base"], "validation completion base"),
        "head": _oid(row["head"], "validation completion head"),
        "hygiene": None,
        "path": path,
        "payload_sha256": _sha(
            row["payload_sha256"], "validation completion payload"),
        "sha256": _sha(row["sha256"], "validation completion file"),
        "size": _nonnegative_int(row["size"], "validation completion size"),
    }
    hygiene = _exact_keys(
        row["hygiene"], {"path", "sha256", "size"},
        "validation completion hygiene")
    parsed_hygiene = {
        "path": _safe_rel(hygiene["path"], "validation hygiene path"),
        "sha256": _sha(hygiene["sha256"], "validation hygiene digest"),
        "size": _nonnegative_int(hygiene["size"], "validation hygiene size"),
    }
    parsed["hygiene"] = parsed_hygiene
    for binding, label in ((parsed, "completion"),
                           (parsed_hygiene, "hygiene")):
        artifact = artifacts.get(binding["path"])
        if (artifact is None or artifact["sha256"] != binding["sha256"]
                or artifact["size"] != binding["size"]):
            raise Refusal(f"validation {label} is not bound to an artifact row")
    return parsed


def _completion_authority(value: Any, arm: str) -> dict[str, Any] | None:
    if value is None:
        if arm in LANDING_ARMS:
            raise Refusal("landing validation has no completion authority")
        return None
    if arm not in LANDING_ARMS:
        raise Refusal("pytest validation unexpectedly has a completion authority")
    return _digest_record(
        value, "validation completion authority", path=True)


def parse_record(value: Any) -> dict[str, Any]:
    record = _exact_keys(value, {
        "complete", "kind", "payload", "payload_sha256", "schema",
    }, "hermetic arm validation record")
    if (type(record["schema"]) is not int or record["schema"] != SCHEMA
            or record["kind"] != KIND or record["complete"] is not True):
        raise Refusal("hermetic arm validation record has the wrong envelope")
    payload = _exact_keys(record["payload"], {
        "arm", "artifacts", "benchmark_data_sha", "command", "completion",
        "completion_authority", "inputs", "mount_sources", "output_dir",
        "receipt", "result_exit_code", "runner",
    }, "hermetic arm validation payload")
    arm = payload["arm"]
    if arm not in ARMS:
        raise Refusal("validation arm is unknown")
    artifacts = _artifact_manifest(payload["artifacts"])
    artifacts_by_path = {row["path"]: row for row in artifacts["files"]}
    mount_sources = _exact_keys(payload["mount_sources"], {
        "corpus", "runtime", "selection", "subject",
    }, "validation mount sources")
    parsed_mounts = {
        key: _absolute_path(mount_sources[key], f"validation {key} mount")
        for key in sorted(mount_sources)
    }
    receipt = _exact_keys(payload["receipt"], {
        "path", "receipt_sha256", "sha256", "size",
    }, "validation receipt binding")
    parsed_receipt = {
        "path": _absolute_path(receipt["path"], "validation receipt path"),
        "receipt_sha256": _sha(
            receipt["receipt_sha256"], "validation claimed receipt digest"),
        "sha256": _sha(receipt["sha256"], "validation receipt file digest"),
        "size": _nonnegative_int(receipt["size"], "validation receipt size"),
    }
    runner = _digest_record(payload["runner"], "validation runner", path=True)
    exit_code = payload["result_exit_code"]
    if type(exit_code) is not int or exit_code not in {0, 1}:
        raise Refusal("validation result is not a natural 0/1 exit")
    parsed_payload = {
        "arm": arm,
        "artifacts": artifacts,
        "benchmark_data_sha": _oid(
            payload["benchmark_data_sha"], "validation benchmark SHA"),
        "command": _command(payload["command"]),
        "completion": _completion_record(
            payload["completion"], artifacts_by_path, arm),
        "completion_authority": _completion_authority(
            payload["completion_authority"], arm),
        "inputs": _inputs_record(payload["inputs"]),
        "mount_sources": parsed_mounts,
        "output_dir": _absolute_path(
            payload["output_dir"], "validation output directory"),
        "receipt": parsed_receipt,
        "result_exit_code": exit_code,
        "runner": runner,
    }
    digest = _sha(record["payload_sha256"], "validation payload digest")
    if digest != _sha256(canonical_bytes(parsed_payload)):
        raise Refusal("validation payload digest differs")
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "complete": True,
        "payload": parsed_payload,
        "payload_sha256": digest,
    }


def strict_load_record(path: Path) -> dict[str, Any]:
    raw, _info = _read_regular(
        path, "hermetic arm validation record", limit=MAX_JSON_BYTES)
    record = parse_record(strict_loads(raw, what="hermetic arm validation record"))
    if raw != canonical_bytes(record):
        raise Refusal("hermetic arm validation record is not canonical JSON")
    return record


def _mount_by_role(receipt: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    rows = [row for row in receipt["container"]["mounts"]
            if row["role"] == role]
    if len(rows) != 1:
        raise Refusal(f"receipt does not have exactly one {role} mount")
    return rows[0]


def _assert_artifact_files(root: Path, manifest: Mapping[str, Any]) -> None:
    for row in manifest["files"]:
        source = root.joinpath(*PurePosixPath(row["path"]).parts)
        raw, info = _read_regular(source, f"artifact {row['path']}")
        mode = "100755" if info.st_mode & 0o111 else "100644"
        if (mode != row["mode"] or len(raw) != row["size"]
                or _sha256(raw) != row["sha256"]):
            raise Refusal(f"artifact {row['path']} differs from its receipt row")


def _artifact_digest(root: Path, rel: str, what: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(rel).parts)
    raw, info = _read_regular(path, what)
    return {
        "mode": "100755" if info.st_mode & 0o111 else "100644",
        "path": rel,
        "sha256": _sha256(raw),
        "size": len(raw),
    }


def validate(
    *,
    runner_path: Path,
    receipt_path: Path,
    output_dir: Path,
    arm: str,
    subject: Path,
    runtime: Path,
    corpus: Path,
    selection: Path,
    progress_plan: Path,
    benchmark_sha: str,
    command: str,
    completion: str | None = None,
    base: str | None = None,
    head: str | None = None,
    hygiene: str | None = None,
) -> dict[str, Any]:
    if arm not in ARMS:
        raise Refusal("arm must be A1, B1, A2, or B2")
    benchmark = _oid(benchmark_sha, "benchmark SHA")
    exact_command = _command([command])
    if arm in LANDING_ARMS:
        if (completion is None or base is None or head is None
                or hygiene is None):
            raise Refusal(
                "A2/B2 require --completion, --base, --head, and --hygiene")
        completion_rel = _safe_rel(completion, "completion artifact")
        hygiene_rel = _safe_rel(hygiene, "hygiene artifact")
        base_oid = _oid(base, "landing base")
        head_oid = _oid(head, "landing head")
    else:
        if any(value is not None for value in (completion, base, head, hygiene)):
            raise Refusal("A1/B1 do not accept landing-completion bindings")
        completion_rel = hygiene_rel = None
        base_oid = head_oid = None

    runner, runner_file, runner_binding = _load_exact_module(
        runner_path, "hermetic candidate runner")
    required = (
        "_artefact_manifest", "_canonical", "_file_digest", "_overlay_paths",
        "_receipt_process_env", "_sha256", "_tree_digest",
        "_load_progress_plan", "strict_load_receipt",
    )
    if any(not callable(getattr(runner, name, None)) for name in required):
        raise Refusal("exact runner lacks its strict receipt/digest API")
    if (getattr(runner, "SCHEMA", None) != SCHEMA
            or getattr(runner, "CORPUS_PATH", None) != "/corpus"):
        raise Refusal("exact runner constants differ from the receipt schema")

    receipt_file = _resolved_file(receipt_path, "runner receipt")
    receipt_before, receipt_raw_before = _file_binding(
        receipt_file, "runner receipt", limit=MAX_JSON_BYTES)
    try:
        receipt = runner.strict_load_receipt(receipt_file)
    except Exception as exc:
        raise Refusal(f"exact runner refused its receipt: {exc}") from exc
    receipt_after, receipt_raw_after = _file_binding(
        receipt_file, "runner receipt", limit=MAX_JSON_BYTES)
    if (receipt_before != receipt_after
            or receipt_raw_before != receipt_raw_after):
        raise Refusal("runner receipt changed while strict-loaded")

    subject_root = _resolved_directory(subject, "subject")
    runtime_root = _resolved_directory(runtime, "runtime")
    corpus_root = _resolved_directory(corpus, "corpus")
    selection_file = _resolved_file(selection, "selection")
    plan_file = _resolved_file(progress_plan, "progress plan")
    output_root = _resolved_directory(output_dir, "output directory")

    try:
        parent_plan, parent_plan_digest = runner._load_progress_plan(plan_file)
        observed_inputs = {
            "subject": runner._tree_digest(subject_root, "subject"),
            "runtime": runner._tree_digest(runtime_root, "runtime"),
            "corpus": runner._tree_digest(corpus_root, "corpus"),
            "selection": runner._file_digest(selection_file),
            "progress_plan": parent_plan_digest,
        }
    except Exception as exc:
        raise Refusal(f"cannot recompute runner input digests: {exc}") from exc

    inputs = receipt["inputs"]
    for name in ("subject", "runtime", "corpus", "selection", "progress_plan"):
        if inputs[name] != observed_inputs[name]:
            raise Refusal(f"receipt {name} digest differs from the current input")

    overlay_paths = [row["path"] for row in inputs["overlays"]]
    expected_overlays = (
        [
            "tools/ci/hermetic_test_arm_entry.sh",
            "vibe-ic-marketplace/plugins/vibe-ic/programs/"
            "matrix_mutation_ledger.py",
            "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
            "test_flow_matrix_census_freshness.py",
            "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
            "test_flow_matrix_coverage.py",
            "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
            "test_matrix_artefact_mutation_channel.py",
            "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
            "test_matrix_mutation_ledger.py",
        ]
        if arm in {"A1", "B1"}
        else ["tools/gatekeeper-land.sh"]
    )
    if overlay_paths != expected_overlays:
        raise Refusal("receipt does not use the exact arm runtime overlays")
    try:
        observed_overlay_rows = runner._overlay_paths(
            overlay_paths, runtime_root, subject_root)
    except Exception as exc:
        raise Refusal(f"cannot recompute runtime overlays: {exc}") from exc
    observed_overlays = [{
        "destination": row["destination"],
        "path": row["path"],
        "source_file": row["source_file"],
    } for row in observed_overlay_rows]
    if observed_overlays != inputs["overlays"]:
        raise Refusal("receipt runtime overlay digests differ")
    observed_inputs["overlays"] = observed_overlays

    try:
        env = runner._receipt_process_env(
            receipt["container"]["process_environment"])
    except Exception as exc:
        raise Refusal(f"receipt process environment is not exact: {exc}") from exc
    if (env.get("GATEKEEPER_VERIFY_ARM") != arm
            or env.get("GATEKEEPER_BENCHMARK_DATA_SHA") != benchmark
            or env.get("VIBE_IC_BENCHMARK_DATA") != runner.CORPUS_PATH):
        raise Refusal("receipt arm/benchmark/VIBE corpus environment differs")
    if receipt["container"]["command"] != exact_command:
        raise Refusal("receipt command differs")
    if (parent_plan["scope"] != receipt["progress"]["scope"]
            or parent_plan["units"] != receipt["progress"]["units"]):
        raise Refusal("receipt progress does not bind the parent progress plan")
    runtime_plan = {
        "nonce": env["VIBEIC_HERMETIC_PROGRESS_NONCE"],
        "protocol": "VIBEIC_PROGRESS/1",
        "schema": runner.SCHEMA,
        "scope": receipt["progress"]["scope"],
        "units": receipt["progress"]["units"],
    }
    runtime_plan_raw = runner._canonical(runtime_plan) + b"\n"
    runtime_plan_digest = {
        "sha256": runner._sha256(runtime_plan_raw),
        "size": len(runtime_plan_raw),
    }
    if inputs["runtime_progress_plan"] != runtime_plan_digest:
        raise Refusal("receipt runtime progress-plan digest differs")
    observed_inputs["runtime_progress_plan"] = runtime_plan_digest

    direct_mounts = {
        "subject": subject_root,
        "runtime": runtime_root,
        "corpus": corpus_root,
        "selection": selection_file,
    }
    for role, expected in direct_mounts.items():
        mount = _mount_by_role(receipt, role)
        if mount["source"] != str(expected):
            raise Refusal(f"receipt {role} mount source differs")
    for row in observed_overlays:
        role = f"runtime_overlay:{row['path']}"
        mount = _mount_by_role(receipt, role)
        expected_source = runtime_root.joinpath(
            *PurePosixPath(row["path"]).parts)
        if mount["source"] != str(expected_source):
            raise Refusal(f"receipt {role} mount source differs")
    progress_mount = _mount_by_role(receipt, "progress_plan")
    progress_source = Path(progress_mount["source"])
    if (not progress_source.is_absolute()
            or progress_source.name != "progress-plan.json"
            or progress_source.parent.parent != Path("/tmp")
            or not progress_source.parent.name.startswith("vibeic-hermetic-")):
        raise Refusal("receipt runtime progress-plan mount source differs")

    try:
        observed_manifest = runner._artefact_manifest(output_root)
    except Exception as exc:
        raise Refusal(f"cannot recompute output artifact manifest: {exc}") from exc
    if observed_manifest != receipt["artifacts"]:
        raise Refusal("output artifact manifest differs from the runner receipt")
    _assert_artifact_files(output_root, observed_manifest)
    try:
        if runner._artefact_manifest(output_root) != observed_manifest:
            raise Refusal("output artifact manifest changed while validated")
    except Refusal:
        raise
    except Exception as exc:
        raise Refusal(f"cannot seal output artifact manifest: {exc}") from exc

    exit_code = receipt["result"]["exit_code"]
    if type(exit_code) is not int or exit_code not in {0, 1}:
        raise Refusal("candidate did not exit naturally with exact status 0 or 1")

    completion_binding: dict[str, Any] | None = None
    completion_authority: dict[str, Any] | None = None
    if arm in LANDING_ARMS:
        if (completion_rel is None or hygiene_rel is None
                or base_oid is None or head_oid is None):
            raise Refusal("internal landing completion binding is incomplete")
        if env.get("GATEKEEPER_BASE") != base_oid:
            raise Refusal("receipt landing base environment differs")
        if (env.get("VIBEIC_LANDING_COMPLETION")
                != f"/evidence/{completion_rel}"):
            raise Refusal("receipt landing completion environment differs")
        if env.get("GATEKEEPER_HYGIENE_REPORT") != f"/evidence/{hygiene_rel}":
            raise Refusal("receipt hygiene environment differs")
        completion_module_path = runner_file.with_name(
            "landing_completion_record.py")
        completion_module, _completion_file, completion_authority = (
            _load_exact_module(
                completion_module_path, "landing completion record"))
        if not callable(getattr(completion_module, "strict_load_record", None)):
            raise Refusal("exact completion module lacks strict_load_record")
        completion_path = output_root.joinpath(
            *PurePosixPath(completion_rel).parts)
        try:
            completion_record = completion_module.strict_load_record(
                completion_path)
        except Exception as exc:
            raise Refusal(f"exact completion module refused the record: {exc}") from exc
        completion_row = _artifact_digest(
            output_root, completion_rel, "landing completion artifact")
        hygiene_row = _artifact_digest(
            output_root, hygiene_rel, "landing hygiene artifact")
        artifacts_by_path = {
            row["path"]: row for row in observed_manifest["files"]}
        if (artifacts_by_path.get(completion_rel) != completion_row
                or artifacts_by_path.get(hygiene_rel) != hygiene_row):
            raise Refusal("completion/hygiene file differs from its artifact row")
        completion_payload = completion_record["payload"]
        selection_digest = {
            key: inputs["selection"][key] for key in ("sha256", "size")
        }
        hygiene_digest = {
            key: hygiene_row[key] for key in ("sha256", "size")
        }
        if (completion_payload["arm"] != arm
                or completion_payload["base"] != base_oid
                or completion_payload["benchmark_data_sha"] != benchmark
                or completion_payload["head"] != head_oid
                or completion_payload["returncode"] != exit_code
                or completion_payload["selection"] != selection_digest
                or completion_payload["progress_plan"] != runtime_plan_digest
                or completion_payload["hygiene"] != hygiene_digest
                or completion_payload["progress_nonce"]
                != env["VIBEIC_LANDING_PROGRESS_NONCE"]):
            raise Refusal("landing completion binding differs")
        completion_binding = {
            "base": base_oid,
            "head": head_oid,
            "hygiene": {
                "path": hygiene_rel,
                **hygiene_digest,
            },
            "path": completion_rel,
            "payload_sha256": completion_record["payload_sha256"],
            "sha256": completion_row["sha256"],
            "size": completion_row["size"],
        }
    final_runner_binding, final_runner_raw = _file_binding(
        runner_file, "hermetic candidate runner", limit=MAX_JSON_BYTES * 4)
    if (final_runner_binding["sha256"] != runner_binding["sha256"]
            or final_runner_binding["size"] != runner_binding["size"]):
        raise Refusal("exact runner changed during validation")
    del final_runner_raw

    payload = {
        "arm": arm,
        "artifacts": observed_manifest,
        "benchmark_data_sha": benchmark,
        "command": exact_command,
        "completion": completion_binding,
        "completion_authority": completion_authority,
        "inputs": observed_inputs,
        "mount_sources": {
            key: str(direct_mounts[key]) for key in sorted(direct_mounts)
        },
        "output_dir": str(output_root),
        "receipt": {
            "path": str(receipt_file),
            "receipt_sha256": receipt["receipt_sha256"],
            **receipt_after,
        },
        "result_exit_code": exit_code,
        "runner": runner_binding,
    }
    record = {
        "schema": SCHEMA,
        "kind": KIND,
        "complete": True,
        "payload": payload,
        "payload_sha256": _sha256(canonical_bytes(payload)),
    }
    return parse_record(record)


def _atomic_write_new(path: Path, raw: bytes, what: str) -> None:
    try:
        parent = path.parent.resolve(strict=True)
        parent_info = parent.lstat()
    except OSError as exc:
        raise Refusal(f"cannot resolve {what} parent: {exc}") from exc
    if not stat.S_ISDIR(parent_info.st_mode):
        raise Refusal(f"{what} parent is not a directory")
    target = parent / path.name
    if target.exists() or target.is_symlink():
        raise Refusal(f"{what} destination already exists")
    temporary = parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_CLOEXEC", 0))
    fd = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(f"short {what} write")
            view = view[written:]
        os.fsync(fd)
        if target.exists() or target.is_symlink():
            raise Refusal(f"{what} destination appeared during publication")
        os.replace(temporary, target)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    observed = target.lstat()
    if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()):
        raise Refusal(f"published {what} is not a parent-owned mode-0600 file")


def write_record(path: Path, record: Mapping[str, Any]) -> None:
    parsed = parse_record(record)
    _atomic_write_new(path, canonical_bytes(parsed), "validation record")


def publish(*, record_path: Path, output_dir: Path, artifact: str,
            destination: Path) -> dict[str, Any]:
    record = strict_load_record(record_path)
    rel = _safe_rel(artifact, "artifact to publish")
    output_root = _resolved_directory(output_dir, "output directory")
    if str(output_root) != record["payload"]["output_dir"]:
        raise Refusal("publish output directory differs from the validation record")
    rows = [row for row in record["payload"]["artifacts"]["files"]
            if row["path"] == rel]
    if len(rows) != 1:
        raise Refusal("artifact is not one exact validation-record row")
    source = output_root.joinpath(*PurePosixPath(rel).parts)
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise Refusal(f"cannot resolve artifact to publish: {exc}") from exc
    if resolved_source != source:
        raise Refusal("artifact to publish traverses a symlink")
    raw, info = _read_regular(source, f"artifact {rel}")
    row = rows[0]
    mode = "100755" if info.st_mode & 0o111 else "100644"
    if (mode != row["mode"] or len(raw) != row["size"]
            or _sha256(raw) != row["sha256"]):
        raise Refusal("artifact digest/mode differs from the validation record")
    _atomic_write_new(destination, raw, "published artifact")
    return {
        "artifact": rel,
        "destination": str(destination.resolve(strict=True)),
        "sha256": row["sha256"],
        "size": row["size"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="operation", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--runner", type=Path, required=True)
    check.add_argument("--receipt", type=Path, required=True)
    check.add_argument("--output-dir", type=Path, required=True)
    check.add_argument("--arm", choices=sorted(ARMS), required=True)
    check.add_argument("--subject", type=Path, required=True)
    check.add_argument("--runtime", type=Path, required=True)
    check.add_argument("--corpus", type=Path, required=True)
    check.add_argument("--selection", type=Path, required=True)
    check.add_argument("--progress-plan", type=Path, required=True)
    check.add_argument("--benchmark-sha", required=True)
    check.add_argument("--command", required=True)
    check.add_argument("--completion")
    check.add_argument("--base")
    check.add_argument("--head")
    check.add_argument("--hygiene")
    check.add_argument("--record", type=Path, required=True)
    seal = sub.add_parser("publish")
    seal.add_argument("--record", type=Path, required=True)
    seal.add_argument("--output-dir", type=Path, required=True)
    seal.add_argument("--artifact", required=True)
    seal.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "validate":
            record = validate(
                runner_path=args.runner,
                receipt_path=args.receipt,
                output_dir=args.output_dir,
                arm=args.arm,
                subject=args.subject,
                runtime=args.runtime,
                corpus=args.corpus,
                selection=args.selection,
                progress_plan=args.progress_plan,
                benchmark_sha=args.benchmark_sha,
                command=args.command,
                completion=args.completion,
                base=args.base,
                head=args.head,
                hygiene=args.hygiene,
            )
            write_record(args.record, record)
            print(
                f"[PASS] hermetic arm {args.arm}: "
                f"exit={record['payload']['result_exit_code']} "
                f"receipt={record['payload']['receipt']['receipt_sha256'][:12]}")
        else:
            result = publish(
                record_path=args.record,
                output_dir=args.output_dir,
                artifact=args.artifact,
                destination=args.destination,
            )
            print(
                f"[PASS] published {result['artifact']}: "
                f"{result['sha256'][:12]}")
    except (ImportError, OSError, Refusal, TypeError, ValueError) as exc:
        print(f"[NORECORD] hermetic landing arm receipt: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
