#!/usr/bin/env python3
"""Validate one base-authorised, atomic landing-runtime transition.

The candidate never supplies this policy.  The merge verifier executes the
copy from the exact BASE commit and this module reads the manifest from that
same commit's object database.  A candidate may therefore keep the complete
protected tuple unchanged, prepare a future tuple without activating it, or
activate the one tuple already authorised by BASE.  Per-file mixtures refuse.
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
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = 1
MANIFEST_KIND = "vibeic.protected-landing-transition"
RECEIPT_KIND = "vibeic.protected-landing-transition-receipt"
BOOTSTRAP_RECEIPT_KIND = "vibeic.protected-landing-bootstrap-receipt"
MANIFEST_PATH = "tools/ci/protected_landing_transition.json"
MAX_JSON_BYTES = 1024 * 1024
ROLE_VALUES = frozenset({"authority", "runtime"})
OPERATION_VALUES = frozenset({"STEADY", "PREPARE", "ACTIVATE"})
ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
HEX_RE = re.compile(r"[0-9a-f]+\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
IMAGE_RE = re.compile(
    r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}\Z")
RUNNER_IMAGE = (
    "ghcr.io/vibeic/vibeic-eda@"
    "sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff"
)

RUNTIME_PATHS = frozenset({
    "tools/gatekeeper-land.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/pytest_per_file_junit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_pytest_progress_plugin.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_watchdog.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})

# This is the minimum trusted closure.  A manifest may name more imported
# modules, but it may not omit one of these and still call itself complete.
REQUIRED_AUTHORITY_PATHS = frozenset({
    "tools/gatekeeper-verify-merge.sh",
    "tools/ci/protected_landing_transition.py",
    "tools/ci/protected_runtime_snapshot.py",
    "tools/ci/trusted_worktree_attest.py",
    "tools/ci/owned_command.py",
    "tools/ci/benchmark_data_landing_checkout.py",
    "tools/ci/hermetic_candidate_runner.py",
    "tools/ci/hermetic_git_subject.py",
    "tools/ci/hermetic_landing_arm_receipt.py",
    "tools/ci/hermetic_progress_emit.py",
    "tools/ci/hermetic_test_arm_entry.sh",
    "tools/ci/landing_completion_record.py",
    "tools/ci/routed_def_corpus.py",
    "tools/ci/trusted_test_selection.py",
    "tools/ci/_gate_dispatch.sh",
    "tools/ci/repo_hygiene_gates.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/hygiene_finding_delta.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_targeted_test_select.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_owned_process_supervisor.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_semantic_child_progress.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_atomic_artefact.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/gate_process_attestation.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_watchdog.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_corpus_location.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_crash_safe_scratch.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_prose_polarity.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_routed_checker_progress.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/drc_vacuous_pass_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/hygiene_shard_plan.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/macro_obs_geometry_intersect_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/policy_direction_pin_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_internal_fail_bubble_up_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_metrics.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_acceptance.json",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_gate.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})


class Refusal(RuntimeError):
    """The requested transition is not completely measured or authorised."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in out:
            raise Refusal(f"duplicate or non-string JSON key {key!r}")
        out[key] = value
    return out


def _reject_constant(value: str) -> Any:
    raise Refusal(f"non-finite JSON number {value!r}")


def strict_loads(raw: bytes | str, *, what: str) -> Any:
    if isinstance(raw, bytes):
        if len(raw) > MAX_JSON_BYTES:
            raise Refusal(f"{what} exceeds {MAX_JSON_BYTES} bytes")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise Refusal(f"{what} is not strict UTF-8") from exc
    else:
        text = raw
        if len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise Refusal(f"{what} exceeds {MAX_JSON_BYTES} bytes")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Refusal(f"{what} is not strict JSON: {exc}") from exc


def canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise Refusal(f"record is not canonically serialisable: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _exact_keys(value: Any, keys: Iterable[str], what: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        got = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise Refusal(f"{what} has the wrong schema: {got!r}")
    return value


def _safe_path(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise Refusal(f"{what} is not a safe repository path")
    pure = PurePosixPath(value)
    if (pure.is_absolute() or value != pure.as_posix()
            or any(part in {"", ".", ".."} for part in pure.parts)):
        raise Refusal(f"{what} is not a canonical relative path: {value!r}")
    return value


def _state_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise Refusal(f"{what} is not a canonical state/transition id")
    return value


def _oid(value: Any, oid_len: int, what: str) -> str:
    if (not isinstance(value, str) or len(value) != oid_len
            or HEX_RE.fullmatch(value) is None):
        raise Refusal(f"{what} is not a lowercase {oid_len}-hex object id")
    return value


def _sha256_value(value: Any, what: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise Refusal(f"{what} is not one lowercase SHA-256 digest")
    return value


def _file_record(value: Any, oid_len: int, what: str) -> dict[str, Any]:
    row = _exact_keys(
        value, {"path", "mode", "blob_oid", "sha256", "size"}, what)
    path = _safe_path(row["path"], f"{what}.path")
    mode = row["mode"]
    if mode not in {"100644", "100755"}:
        raise Refusal(f"{what}.mode must describe a regular tracked file")
    blob_oid = _oid(row["blob_oid"], oid_len, f"{what}.blob_oid")
    sha256 = row["sha256"]
    if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
        raise Refusal(f"{what}.sha256 is not lowercase sha256")
    size = row["size"]
    if type(size) is not int or size < 0:
        raise Refusal(f"{what}.size is not a nonnegative integer")
    return {"path": path, "mode": mode, "blob_oid": blob_oid,
            "sha256": sha256, "size": size}


def _roles_row(value: Any, what: str) -> dict[str, Any]:
    row = _exact_keys(value, {"path", "roles"}, what)
    path = _safe_path(row["path"], f"{what}.path")
    roles = row["roles"]
    if (not isinstance(roles, list) or not roles
            or any(not isinstance(role, str) or role not in ROLE_VALUES
                   for role in roles)
            or roles != sorted(set(roles))):
        raise Refusal(f"{what}.roles must be a sorted unique role list")
    return {"path": path, "roles": list(roles)}


def _runner_profile(value: Any, what: str = "manifest.runner"
                    ) -> dict[str, Any]:
    row = _exact_keys(
        value,
        {"schema", "profile_id", "engine", "image", "platform", "user",
         "network", "read_only", "cap_drop", "security_opt", "tmpfs",
         "pull", "workdir", "subject_mount", "runtime_mount",
         "corpus_mount", "input_mounts", "runtime_overlays",
         "process_environment", "progress_protocol", "evidence_transport"},
        what,
    )
    if type(row["schema"]) is not int or row["schema"] != 1:
        raise Refusal(f"{what}.schema is not 1")
    profile_id = _state_id(row["profile_id"], f"{what}.profile_id")
    if row["engine"] != "docker":
        raise Refusal(f"{what}.engine is not docker")
    image = row["image"]
    if not isinstance(image, str) or IMAGE_RE.fullmatch(image) is None:
        raise Refusal(f"{what}.image is not an immutable digest reference")
    if image != RUNNER_IMAGE:
        raise Refusal(f"{what}.image is not the BASE-owned runner image")
    expected = {
        "platform": "linux/amd64",
        "user": "65534:65534",
        "network": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": [
            "/tmp:rw,nosuid,nodev,noexec,size=536870912,mode=1777"],
        "pull": "never",
        "workdir": "/subject",
        "subject_mount": "read-only",
        "runtime_mount": "read-only",
        "corpus_mount": "read-only",
        "input_mounts": "selection-and-progress-plan-read-only",
        "runtime_overlays": "sorted-exact-files-read-only",
        "process_environment": "env-i-exact-arm-profile",
        "progress_protocol": "VIBEIC_PROGRESS/1",
        "evidence_transport": (
            "private-volume-post-stop-export-and-absence-proof"),
    }
    for key, expected_value in expected.items():
        if row[key] != expected_value:
            raise Refusal(f"{what}.{key} does not match the hermetic profile")
    return {
        "schema": 1,
        "profile_id": profile_id,
        "engine": "docker",
        "image": image,
        **expected,
    }


def _state(value: Any, oid_len: int, what: str) -> dict[str, Any]:
    state = _exact_keys(value, {"id", "files"}, what)
    state_id = _state_id(state["id"], f"{what}.id")
    if not isinstance(state["files"], list):
        raise Refusal(f"{what}.files is not a list")
    files = [_file_record(row, oid_len, f"{what}.files[{index}]")
             for index, row in enumerate(state["files"])]
    paths = [row["path"] for row in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise Refusal(f"{what}.files is not sorted and unique")
    return {"id": state_id, "files": files}


def parse_manifest(value: Any, oid_len: int) -> dict[str, Any]:
    root = _exact_keys(
        value,
        {"schema", "kind", "transition_id", "manifest_path", "runner", "paths",
         "current", "next"},
        "manifest",
    )
    if type(root["schema"]) is not int or root["schema"] != SCHEMA:
        raise Refusal("manifest.schema is not 1")
    if root["kind"] != MANIFEST_KIND:
        raise Refusal("manifest.kind is not the protected transition kind")
    transition_id = _state_id(root["transition_id"], "manifest.transition_id")
    if root["manifest_path"] != MANIFEST_PATH:
        raise Refusal("manifest_path does not name the trusted manifest")
    runner = _runner_profile(root["runner"])
    if not isinstance(root["paths"], list):
        raise Refusal("manifest.paths is not a list")
    paths = [_roles_row(row, f"manifest.paths[{index}]")
             for index, row in enumerate(root["paths"])]
    names = [row["path"] for row in paths]
    if names != sorted(names) or len(names) != len(set(names)):
        raise Refusal("manifest.paths is not sorted and unique")
    if MANIFEST_PATH in names:
        raise Refusal("the manifest cannot recursively include itself")
    role_map = {row["path"]: frozenset(row["roles"]) for row in paths}
    runtime = {path for path, roles in role_map.items() if "runtime" in roles}
    authority = {path for path, roles in role_map.items() if "authority" in roles}
    if runtime != RUNTIME_PATHS:
        raise Refusal("manifest runtime role set is not the exact five-file tuple")
    missing_authority = REQUIRED_AUTHORITY_PATHS - authority
    if missing_authority:
        raise Refusal("manifest omits trusted authority dependencies: "
                      + ", ".join(sorted(missing_authority)))
    current = _state(root["current"], oid_len, "manifest.current")
    next_state = _state(root["next"], oid_len, "manifest.next")
    if current["id"] == next_state["id"]:
        raise Refusal("manifest current and next state ids are equal")
    if [row["path"] for row in current["files"]] != names:
        raise Refusal("manifest.current does not exactly cover manifest.paths")
    if [row["path"] for row in next_state["files"]] != names:
        raise Refusal("manifest.next does not exactly cover manifest.paths")
    if current["files"] == next_state["files"]:
        raise Refusal("manifest next tuple does not differ from current")
    return {
        "schema": SCHEMA,
        "kind": MANIFEST_KIND,
        "transition_id": transition_id,
        "manifest_path": MANIFEST_PATH,
        "runner": runner,
        "paths": paths,
        "current": current,
        "next": next_state,
    }


def _git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update({"GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C"})
    return env


def _git(repo: Path, args: Sequence[str], *, binary: bool = False) -> bytes | str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=_git_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise Refusal(f"git {' '.join(args[:2])} failed: {detail[:240]}")
    if binary:
        return proc.stdout
    try:
        return proc.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise Refusal("git returned non-ASCII object metadata") from exc


def _object_format(repo: Path) -> tuple[str, int]:
    name = _git(repo, ["rev-parse", "--show-object-format"])
    if name == "sha1":
        return name, 40
    if name == "sha256":
        return name, 64
    raise Refusal(f"unsupported Git object format {name!r}")


def _commit_and_tree(repo: Path, rev: str, oid_len: int,
                     what: str) -> tuple[str, str]:
    commit = _oid(_git(repo, ["rev-parse", f"{rev}^{{commit}}"]),
                  oid_len, f"{what} commit")
    tree = _oid(_git(repo, ["rev-parse", f"{commit}^{{tree}}"]),
                oid_len, f"{what} tree")
    return commit, tree


def _tree(repo: Path, commit: str, oid_len: int
          ) -> dict[str, tuple[str, str]]:
    raw = _git(repo, ["ls-tree", "-rz", "--full-tree", commit], binary=True)
    assert isinstance(raw, bytes)
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, raw_path = record.split(b"\t", 1)
            raw_mode, kind, raw_oid = meta.split()
            mode = raw_mode.decode("ascii")
            entry_kind = kind.decode("ascii")
            oid = raw_oid.decode("ascii")
            path = os.fsdecode(raw_path)
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal("malformed ls-tree record") from exc
        _safe_path(path, "tree entry")
        _oid(oid, oid_len, f"tree entry {path}")
        if entry_kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise Refusal(f"unsupported tree entry {path!r} ({mode} {entry_kind})")
        if path in entries:
            raise Refusal(f"duplicate tree path {path!r}")
        entries[path] = (mode, oid)
    if not entries:
        raise Refusal("commit tree is empty")
    return entries


def _blob_oid(data: bytes, algorithm: str) -> str:
    digest = hashlib.sha1() if algorithm == "sha1" else hashlib.sha256()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _observe_file(repo: Path, path: str, entry: tuple[str, str],
                  algorithm: str, oid_len: int) -> dict[str, Any]:
    mode, oid = entry
    if mode not in {"100644", "100755"}:
        raise Refusal(f"protected path is not a regular file: {path}")
    data = _git(repo, ["cat-file", "blob", oid], binary=True)
    assert isinstance(data, bytes)
    if _blob_oid(data, algorithm) != oid:
        raise Refusal(f"raw blob object disagrees with its id: {path}")
    return {"path": path, "mode": mode, "blob_oid": oid,
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _observe_files(repo: Path, commit: str, paths: Sequence[dict[str, Any]],
                   algorithm: str, oid_len: int) -> list[dict[str, Any]]:
    tree = _tree(repo, commit, oid_len)
    out = []
    for row in paths:
        path = row["path"]
        if path not in tree:
            raise Refusal(f"protected path is absent: {path}")
        out.append(_observe_file(repo, path, tree[path], algorithm, oid_len))
    return out


def _observe_manifest(repo: Path, commit: str, algorithm: str,
                      oid_len: int) -> tuple[dict[str, Any], bytes]:
    tree = _tree(repo, commit, oid_len)
    if MANIFEST_PATH not in tree:
        raise Refusal(f"commit has no {MANIFEST_PATH}")
    record = _observe_file(
        repo, MANIFEST_PATH, tree[MANIFEST_PATH], algorithm, oid_len)
    if record["mode"] != "100644":
        raise Refusal("protected transition manifest must be non-executable")
    raw = _git(repo, ["cat-file", "blob", record["blob_oid"]], binary=True)
    assert isinstance(raw, bytes)
    return record, raw


def _match_state(files: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    if files == manifest["current"]["files"]:
        return manifest["current"]["id"]
    if files == manifest["next"]["files"]:
        return manifest["next"]["id"]
    raise Refusal("protected tuple matches neither authorised atomic state")


def _attest_worktree(repo: Path, worktree: Path, commit: str) -> None:
    # Imported from the same raw-attested BASE authority closure as this file.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import trusted_worktree_attest as attester
    except ImportError as exc:  # pragma: no cover - deployment damage
        raise Refusal("trusted worktree attester cannot be imported") from exc
    try:
        root = worktree.resolve(strict=True)
        if not root.is_dir():
            raise Refusal("candidate worktree is not a directory")
        attester._attest(  # type: ignore[attr-defined]
            root,
            attester._tree(repo, commit),  # type: ignore[attr-defined]
            allow_git_control_file=True,
            object_repo=repo,
            expected_sha=commit,
        )
    except (OSError, attester.Refusal) as exc:  # type: ignore[attr-defined]
        raise Refusal(f"candidate worktree raw attestation failed: {exc}") from exc


def build_receipt(*, object_repo: Path, base: str, candidate: str,
                  candidate_gates: Path, candidate_tests: Path) -> dict[str, Any]:
    repo = object_repo.resolve(strict=True)
    algorithm, oid_len = _object_format(repo)
    base_commit, base_tree = _commit_and_tree(repo, base, oid_len, "base")
    cand_commit, cand_tree = _commit_and_tree(
        repo, candidate, oid_len, "candidate")
    base_manifest_file, base_manifest_raw = _observe_manifest(
        repo, base_commit, algorithm, oid_len)
    cand_manifest_file, cand_manifest_raw = _observe_manifest(
        repo, cand_commit, algorithm, oid_len)
    base_manifest = parse_manifest(
        strict_loads(base_manifest_raw, what="base manifest"), oid_len)
    candidate_manifest = parse_manifest(
        strict_loads(cand_manifest_raw, what="candidate manifest"), oid_len)
    base_files = _observe_files(
        repo, base_commit, base_manifest["paths"], algorithm, oid_len)
    base_state_id = _match_state(base_files, base_manifest)
    candidate_files = _observe_files(
        repo, cand_commit, base_manifest["paths"], algorithm, oid_len)

    if cand_manifest_raw == base_manifest_raw:
        candidate_state_id = _match_state(candidate_files, base_manifest)
        if candidate_state_id == base_state_id:
            operation = "STEADY"
        elif (base_state_id == base_manifest["current"]["id"]
              and candidate_state_id == base_manifest["next"]["id"]):
            operation = "ACTIVATE"
        else:
            raise Refusal("protected tuple attempts a rollback or unprepared move")
    else:
        operation = "PREPARE"
        if candidate_files != base_files:
            raise Refusal("PREPARE changed live protected bytes with the manifest")
        if candidate_manifest["paths"] != base_manifest["paths"]:
            raise Refusal("PREPARE changed the protected path/role set")
        if candidate_manifest["runner"] != base_manifest["runner"]:
            raise Refusal("PREPARE changed the hermetic runner profile")
        if candidate_manifest["transition_id"] == base_manifest["transition_id"]:
            raise Refusal("PREPARE did not allocate a new transition id")
        if candidate_manifest["current"]["id"] != base_state_id:
            raise Refusal("PREPARE current state id does not name the live base")
        if candidate_manifest["current"]["files"] != base_files:
            raise Refusal("PREPARE current tuple is not the exact live base tuple")
        if candidate_manifest["next"]["id"] == base_manifest["next"]["id"]:
            raise Refusal("PREPARE did not allocate a new next state id")
        candidate_state_id = base_state_id

    _attest_worktree(repo, candidate_gates, cand_commit)
    _attest_worktree(repo, candidate_tests, cand_commit)
    role_map = {row["path"]: list(row["roles"])
                for row in base_manifest["paths"]}
    base_observed = [{**row, "roles": role_map[row["path"]]}
                     for row in base_files]
    candidate_observed = [{**row, "roles": role_map[row["path"]]}
                          for row in candidate_files]
    payload = {
        "operation": operation,
        "base_commit": base_commit,
        "base_tree": base_tree,
        "candidate_commit": cand_commit,
        "candidate_tree": cand_tree,
        "base_manifest": base_manifest_file,
        "candidate_manifest": cand_manifest_file,
        "runner": base_manifest["runner"],
        "base_transition_id": base_manifest["transition_id"],
        "candidate_transition_id": candidate_manifest["transition_id"],
        "base_current_state_id": base_manifest["current"]["id"],
        "base_next_state_id": base_manifest["next"]["id"],
        "base_state_id": base_state_id,
        "candidate_state_id": candidate_state_id,
        "base_files": base_observed,
        "candidate_files": candidate_observed,
        "worktrees": [
            {"role": "candidate-gates", "commit": cand_commit,
             "tree": cand_tree, "complete": True},
            {"role": "candidate-tests", "commit": cand_commit,
             "tree": cand_tree, "complete": True},
        ],
    }
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return {"schema": SCHEMA, "kind": RECEIPT_KIND, "complete": True,
            "payload": payload, "payload_sha256": digest}


def build_bootstrap_receipt(*, object_repo: Path, trusted_base: str,
                            phase_a: str, old_verdict: Path,
                            old_hygiene_summary: Path) -> dict[str, Any]:
    """Record the one landing before this validator itself is BASE-owned.

    This is operator evidence, not a way for a candidate to authorize itself.
    It proves the old trusted verifier judged a phase-A tree whose live runtime
    bytes did not move, while naming the exact authority and future tuple that
    only a later BASE-owned validator may activate.
    """
    repo = object_repo.resolve(strict=True)
    algorithm, oid_len = _object_format(repo)
    base_commit, base_tree = _commit_and_tree(
        repo, trusted_base, oid_len, "trusted base")
    phase_commit, phase_tree = _commit_and_tree(
        repo, phase_a, oid_len, "phase A")
    base_entries = _tree(repo, base_commit, oid_len)
    if MANIFEST_PATH in base_entries:
        raise Refusal("bootstrap base already carries a transition manifest")
    phase_manifest_file, phase_manifest_raw = _observe_manifest(
        repo, phase_commit, algorithm, oid_len)
    manifest = parse_manifest(
        strict_loads(phase_manifest_raw, what="phase-A manifest"), oid_len)
    phase_files = _observe_files(
        repo, phase_commit, manifest["paths"], algorithm, oid_len)
    if phase_files != manifest["current"]["files"]:
        raise Refusal("phase-A live tuple is not the manifest current state")
    role_map = {row["path"]: list(row["roles"])
                for row in manifest["paths"]}

    protected_unchanged = []
    for path in sorted(RUNTIME_PATHS):
        if path not in base_entries:
            raise Refusal(f"trusted base omits protected runtime {path}")
        base_file = _observe_file(
            repo, path, base_entries[path], algorithm, oid_len)
        phase_file = next(row for row in phase_files if row["path"] == path)
        if base_file != phase_file:
            raise Refusal(f"phase A changed protected runtime bytes: {path}")
        protected_unchanged.append({**phase_file, "roles": role_map[path]})

    phase_authority = [
        {**row, "roles": role_map[row["path"]]}
        for row in phase_files if "authority" in role_map[row["path"]]
    ]
    verifier_path = "tools/gatekeeper-verify-merge.sh"
    if verifier_path not in base_entries:
        raise Refusal("trusted base has no merge verifier")
    trusted_verifier = _observe_file(
        repo, verifier_path, base_entries[verifier_path], algorithm, oid_len)

    try:
        verdict_raw = old_verdict.read_bytes()
        hygiene_raw = old_hygiene_summary.read_bytes()
    except OSError as exc:
        raise Refusal(f"bootstrap evidence is unreadable: {exc}") from exc
    verdict = strict_loads(verdict_raw, what="old verifier verdict")
    hygiene = strict_loads(hygiene_raw, what="old hygiene summary")
    verdict_binding = _old_verdict_binding(
        verdict, base_commit=base_commit, phase_commit=phase_commit,
        phase_tree=phase_tree, raw=verdict_raw)
    hygiene_binding = _old_hygiene_binding(hygiene, raw=hygiene_raw)

    payload = {
        "trusted_base_commit": base_commit,
        "trusted_base_tree": base_tree,
        "phase_a_commit": phase_commit,
        "phase_a_tree": phase_tree,
        "trusted_verifier": trusted_verifier,
        "protected_unchanged": protected_unchanged,
        "phase_a_manifest": phase_manifest_file,
        "phase_a_authority": phase_authority,
        "old_verdict": verdict_binding,
        "old_hygiene_summary": hygiene_binding,
        "land_verdict": "LAND_OK",
    }
    return {
        "schema": SCHEMA,
        "kind": BOOTSTRAP_RECEIPT_KIND,
        "complete": True,
        "payload": payload,
        "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def _old_verdict_binding(value: Any, *, base_commit: str,
                         phase_commit: str, phase_tree: str,
                         raw: bytes) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refusal("old verifier verdict is not an object")
    required = {
        "verdict", "base_sha", "head_sha", "verified_sha", "verified_tree",
        "expected_tree", "replayed_tree", "rebase_status", "reasons",
        "unmeasurable", "candidate_run_truncated", "verification_tier",
        "land", "delta",
    }
    missing = required - set(value)
    if missing:
        raise Refusal("old verifier verdict is partial: "
                      + ", ".join(sorted(missing)))
    if (value["verdict"] != "LAND_OK"
            or value["base_sha"] != base_commit
            or value["verified_sha"] != phase_commit
            or value["verified_tree"] != phase_tree
            or value["expected_tree"] != phase_tree
            or value["replayed_tree"] != phase_tree
            or value["rebase_status"] != "ok"
            or value["reasons"] != []
            or value["unmeasurable"] is not False
            or value["candidate_run_truncated"] is not False
            or value["verification_tier"] not in {"merge-tree", "rebase-replay"}
            or not isinstance(value["head_sha"], str)
            or len(value["head_sha"]) != len(base_commit)):
        raise Refusal("old verifier LAND_OK does not completely bind Phase A")
    land = value["land"]
    delta = value["delta"]
    if (not isinstance(land, dict)
            or not {"pass", "fail", "skip", "report"} <= set(land)
            or any(not isinstance(land[key], list)
                   for key in ("pass", "fail", "skip", "report"))
            or not isinstance(delta, dict)
            or not {"new_failures", "silenced", "weakened"} <= set(delta)
            or delta["new_failures"] != [] or delta["silenced"] != []
            or delta["weakened"] != []):
        raise Refusal("old verifier LAND_OK carries incomplete/red evidence")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "base_sha": base_commit,
        "head_sha": value["head_sha"],
        "verified_sha": phase_commit,
        "verified_tree": phase_tree,
        "expected_tree": phase_tree,
        "replayed_tree": phase_tree,
        "rebase_status": "ok",
        "verification_tier": value["verification_tier"],
        "verdict": "LAND_OK",
    }


def _old_hygiene_binding(value: Any, *, raw: bytes) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refusal("old hygiene summary is not an object")
    required = {
        "declared", "ran", "decided", "passed", "failed", "not_checked",
        "wrote_corpus", "deferred", "other_shard", "gates", "corpora",
        "process_attestations", "not_checked_unexempted", "wiring_errors",
        "undisclosed_loops", "exemptions_expired", "listed_only", "shard",
    }
    missing = required - set(value)
    if missing:
        raise Refusal("old hygiene summary is partial: "
                      + ", ".join(sorted(missing)))
    counters = {key: value[key] for key in
                ("declared", "ran", "decided", "passed", "failed",
                 "not_checked", "wrote_corpus", "deferred", "other_shard")}
    if any(type(item) is not int or item < 0 for item in counters.values()):
        raise Refusal("old hygiene counters are not nonnegative integers")
    gates = value["gates"]
    if (not isinstance(gates, list) or not gates
            or not all(isinstance(row, dict)
                       and isinstance(row.get("label"), str)
                       and row.get("state") in
                       {"PASS", "FAIL", "NOT_CHECKED", "WROTE",
                        "OUT_OF_SCOPE", "LISTED", "OTHER_SHARD"}
                       for row in gates)):
        raise Refusal("old hygiene gates are incomplete")
    states = [row["state"] for row in gates]
    exact = {
        "declared": len(gates),
        "ran": sum(state in {"PASS", "FAIL", "NOT_CHECKED", "WROTE"}
                   for state in states),
        "decided": sum(state in {"PASS", "FAIL"} for state in states),
        "passed": states.count("PASS"),
        "failed": states.count("FAIL"),
        "not_checked": states.count("NOT_CHECKED"),
        "wrote_corpus": states.count("WROTE"),
        "deferred": states.count("LISTED"),
        "other_shard": states.count("OTHER_SHARD"),
    }
    if counters != exact:
        raise Refusal("old hygiene counters disagree with gate states")
    if (not isinstance(value["corpora"], list)
            or not isinstance(value["process_attestations"], list)
            or not isinstance(value["not_checked_unexempted"], list)
            or value["wiring_errors"] != []
            or value["undisclosed_loops"] != []
            or value["exemptions_expired"] != []
            or value["listed_only"] is not False
            or value["shard"] is not None):
        raise Refusal("old hygiene summary is structurally incomplete")
    out_of_scope = value.get("out_of_scope", states.count("OUT_OF_SCOPE"))
    if type(out_of_scope) is not int or out_of_scope != states.count("OUT_OF_SCOPE"):
        raise Refusal("old hygiene out_of_scope count disagrees")
    corpus_inputs = value.get("corpus_inputs")
    benchmark_sha = None
    if corpus_inputs is not None:
        if (not isinstance(corpus_inputs, dict)
                or set(corpus_inputs) != {"benchmark_data_sha"}):
            raise Refusal("old hygiene corpus_inputs is ambiguous")
        benchmark_sha = corpus_inputs["benchmark_data_sha"]
        if (benchmark_sha is not None
                and (not isinstance(benchmark_sha, str)
                     or OID_RE.fullmatch(benchmark_sha) is None)):
            raise Refusal("old hygiene benchmark SHA is malformed")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        **counters,
        "out_of_scope": out_of_scope,
        "benchmark_data_sha": benchmark_sha,
        "gates_sha256": hashlib.sha256(canonical_bytes(gates)).hexdigest(),
        "process_attestations_sha256": hashlib.sha256(
            canonical_bytes(value["process_attestations"])).hexdigest(),
    }
def _validate_observed(value: Any, oid_len: int, what: str
                       ) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise Refusal(f"{what} is not a list")
    out = []
    for index, raw in enumerate(value):
        row = _exact_keys(raw, {"path", "mode", "blob_oid", "sha256",
                               "size", "roles"}, f"{what}[{index}]")
        file_row = _file_record(
            {key: row[key] for key in ("path", "mode", "blob_oid",
                                       "sha256", "size")},
            oid_len,
            f"{what}[{index}]",
        )
        roles = _roles_row(
            {"path": row["path"], "roles": row["roles"]},
            f"{what}[{index}]",
        )["roles"]
        out.append({**file_row, "roles": roles})
    paths = [row["path"] for row in out]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise Refusal(f"{what} is not sorted and unique")
    return out


def _parse_receipt(value: Any, oid_len: int) -> dict[str, Any]:
    root = _exact_keys(
        value, {"schema", "kind", "complete", "payload", "payload_sha256"},
        "receipt")
    if type(root["schema"]) is not int or root["schema"] != SCHEMA:
        raise Refusal("receipt.schema is not 1")
    if root["kind"] != RECEIPT_KIND or root["complete"] is not True:
        raise Refusal("receipt is not a complete protected transition record")
    payload = _exact_keys(
        root["payload"],
        {"operation", "base_commit", "base_tree", "candidate_commit",
         "candidate_tree", "base_manifest", "candidate_manifest",
         "runner",
         "base_transition_id", "candidate_transition_id",
         "base_current_state_id", "base_next_state_id", "base_state_id",
         "candidate_state_id", "base_files", "candidate_files", "worktrees"},
        "receipt.payload",
    )
    operation = payload["operation"]
    if operation not in OPERATION_VALUES:
        raise Refusal("receipt operation is unknown")
    for key in ("base_commit", "base_tree", "candidate_commit", "candidate_tree"):
        _oid(payload[key], oid_len, f"receipt.payload.{key}")
    base_manifest = _file_record(
        payload["base_manifest"], oid_len, "receipt.payload.base_manifest")
    candidate_manifest = _file_record(
        payload["candidate_manifest"], oid_len,
        "receipt.payload.candidate_manifest")
    if (base_manifest["path"] != MANIFEST_PATH
            or candidate_manifest["path"] != MANIFEST_PATH):
        raise Refusal("receipt manifest observation names the wrong path")
    runner = _runner_profile(payload["runner"], "receipt.payload.runner")
    for key in ("base_transition_id", "candidate_transition_id",
                "base_current_state_id", "base_next_state_id",
                "base_state_id", "candidate_state_id"):
        _state_id(payload[key], f"receipt.payload.{key}")
    if payload["base_current_state_id"] == payload["base_next_state_id"]:
        raise Refusal("receipt BASE current and next state ids are equal")
    if payload["base_state_id"] not in {
            payload["base_current_state_id"], payload["base_next_state_id"]}:
        raise Refusal("receipt live BASE state is not an authorised state")
    base_files = _validate_observed(
        payload["base_files"], oid_len, "receipt.payload.base_files")
    candidate_files = _validate_observed(
        payload["candidate_files"], oid_len,
        "receipt.payload.candidate_files")
    base_paths = [row["path"] for row in base_files]
    candidate_paths = [row["path"] for row in candidate_files]
    if base_paths != candidate_paths or not base_paths:
        raise Refusal("receipt protected tuples do not exact-cover one path set")
    role_map = {row["path"]: frozenset(row["roles"]) for row in base_files}
    if any(frozenset(row["roles"]) != role_map.get(row["path"])
           for row in candidate_files):
        raise Refusal("receipt candidate roles differ from BASE authority")
    runtime = {path for path, roles in role_map.items() if "runtime" in roles}
    authority = {path for path, roles in role_map.items() if "authority" in roles}
    if runtime != RUNTIME_PATHS or not REQUIRED_AUTHORITY_PATHS <= authority:
        raise Refusal("receipt omits the protected runtime/authority closure")
    worktrees = payload["worktrees"]
    if not isinstance(worktrees, list) or len(worktrees) != 2:
        raise Refusal("receipt worktrees is not the exact two-arm list")
    parsed_worktrees = []
    expected_roles = ("candidate-gates", "candidate-tests")
    for index, role in enumerate(expected_roles):
        row = _exact_keys(
            worktrees[index], {"role", "commit", "tree", "complete"},
            f"receipt.payload.worktrees[{index}]")
        if (row["role"] != role or row["complete"] is not True
                or row["commit"] != payload["candidate_commit"]
                or row["tree"] != payload["candidate_tree"]):
            raise Refusal("receipt worktree binding is incomplete or inconsistent")
        parsed_worktrees.append(dict(row))
    digest = root["payload_sha256"]
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise Refusal("receipt payload_sha256 is malformed")
    expected_digest = hashlib.sha256(canonical_bytes(dict(payload))).hexdigest()
    if digest != expected_digest:
        raise Refusal("receipt payload digest does not match its canonical payload")
    base_transition = payload["base_transition_id"]
    candidate_transition = payload["candidate_transition_id"]
    base_state = payload["base_state_id"]
    candidate_state = payload["candidate_state_id"]
    same_files = base_files == candidate_files
    same_manifest = base_manifest == candidate_manifest
    if operation == "STEADY" and not (
            same_files and same_manifest and base_transition == candidate_transition
            and base_state == candidate_state):
        raise Refusal("STEADY receipt does not describe one unchanged tuple")
    if operation == "ACTIVATE" and not (
            not same_files and same_manifest
            and base_transition == candidate_transition
            and base_state == payload["base_current_state_id"]
            and candidate_state == payload["base_next_state_id"]):
        raise Refusal("ACTIVATE receipt is not one preauthorised atomic move")
    if operation == "PREPARE" and not (
            same_files and not same_manifest
            and base_transition != candidate_transition
            and base_state == candidate_state):
        raise Refusal("PREPARE receipt changed live bytes or kept old authority")
    # Preserve the canonical parsed shape.  These equalities also prevent a
    # caller from relying on bool-as-int or mapping subclasses accepted above.
    return {
        "schema": SCHEMA, "kind": RECEIPT_KIND, "complete": True,
        "payload": {
            **dict(payload),
            "base_manifest": base_manifest,
            "candidate_manifest": candidate_manifest,
            "runner": runner,
            "base_files": base_files,
            "candidate_files": candidate_files,
            "worktrees": parsed_worktrees,
        },
        "payload_sha256": digest,
    }


def _parse_bootstrap_receipt(value: Any, oid_len: int) -> dict[str, Any]:
    root = _exact_keys(
        value, {"schema", "kind", "complete", "payload", "payload_sha256"},
        "bootstrap receipt")
    if (type(root["schema"]) is not int or root["schema"] != SCHEMA
            or root["kind"] != BOOTSTRAP_RECEIPT_KIND
            or root["complete"] is not True):
        raise Refusal("bootstrap receipt is not one complete schema-1 record")
    payload = _exact_keys(
        root["payload"],
        {"trusted_base_commit", "trusted_base_tree", "phase_a_commit",
         "phase_a_tree", "trusted_verifier", "protected_unchanged",
         "phase_a_manifest", "phase_a_authority", "old_verdict",
         "old_hygiene_summary", "land_verdict"},
        "bootstrap receipt.payload")
    for key in ("trusted_base_commit", "trusted_base_tree", "phase_a_commit",
                "phase_a_tree"):
        _oid(payload[key], oid_len, f"bootstrap receipt.payload.{key}")
    trusted_verifier = _file_record(
        payload["trusted_verifier"], oid_len,
        "bootstrap receipt.payload.trusted_verifier")
    if trusted_verifier["path"] != "tools/gatekeeper-verify-merge.sh":
        raise Refusal("bootstrap trusted verifier names another path")
    manifest = _file_record(
        payload["phase_a_manifest"], oid_len,
        "bootstrap receipt.payload.phase_a_manifest")
    if manifest["path"] != MANIFEST_PATH:
        raise Refusal("bootstrap phase-A manifest names another path")
    protected = _validate_observed(
        payload["protected_unchanged"], oid_len,
        "bootstrap receipt.payload.protected_unchanged")
    authority = _validate_observed(
        payload["phase_a_authority"], oid_len,
        "bootstrap receipt.payload.phase_a_authority")
    if {row["path"] for row in protected} != RUNTIME_PATHS:
        raise Refusal("bootstrap does not exact-cover the five old runtime files")
    if any("runtime" not in row["roles"] for row in protected):
        raise Refusal("bootstrap protected file lost its runtime role")
    if not REQUIRED_AUTHORITY_PATHS <= {row["path"] for row in authority}:
        raise Refusal("bootstrap omits the Phase-A authority closure")
    if any("authority" not in row["roles"] for row in authority):
        raise Refusal("bootstrap authority row lacks authority role")
    old_verdict = _exact_keys(
        payload["old_verdict"],
        {"sha256", "base_sha", "head_sha", "verified_sha", "verified_tree",
         "expected_tree", "replayed_tree", "rebase_status",
         "verification_tier", "verdict"},
        "bootstrap receipt.payload.old_verdict")
    _sha256_value(old_verdict["sha256"], "bootstrap old verdict digest")
    for key in ("base_sha", "head_sha", "verified_sha", "verified_tree",
                "expected_tree", "replayed_tree"):
        _oid(old_verdict[key], oid_len,
             f"bootstrap receipt.payload.old_verdict.{key}")
    if (old_verdict["verdict"] != "LAND_OK"
            or old_verdict["rebase_status"] != "ok"
            or old_verdict["verification_tier"] not in
            {"merge-tree", "rebase-replay"}
            or old_verdict["base_sha"] != payload["trusted_base_commit"]
            or old_verdict["verified_sha"] != payload["phase_a_commit"]
            or any(old_verdict[key] != payload["phase_a_tree"] for key in
                   ("verified_tree", "expected_tree", "replayed_tree"))):
        raise Refusal("bootstrap old verdict binding is inconsistent")
    old_hygiene = _exact_keys(
        payload["old_hygiene_summary"],
        {"sha256", "declared", "ran", "decided", "passed", "failed",
         "not_checked", "wrote_corpus", "deferred", "other_shard",
         "out_of_scope", "benchmark_data_sha", "gates_sha256",
         "process_attestations_sha256"},
        "bootstrap receipt.payload.old_hygiene_summary")
    for key in ("sha256", "gates_sha256", "process_attestations_sha256"):
        _sha256_value(old_hygiene[key], f"bootstrap old hygiene {key}")
    for key in ("declared", "ran", "decided", "passed", "failed",
                "not_checked", "wrote_corpus", "deferred", "other_shard",
                "out_of_scope"):
        if type(old_hygiene[key]) is not int or old_hygiene[key] < 0:
            raise Refusal("bootstrap old hygiene counter is malformed")
    benchmark = old_hygiene["benchmark_data_sha"]
    if benchmark is not None and (
            not isinstance(benchmark, str) or OID_RE.fullmatch(benchmark) is None):
        raise Refusal("bootstrap old hygiene benchmark binding is malformed")
    if payload["land_verdict"] != "LAND_OK":
        raise Refusal("bootstrap receipt does not record LAND_OK")
    digest = root["payload_sha256"]
    _sha256_value(digest, "bootstrap payload digest")
    if digest != hashlib.sha256(canonical_bytes(dict(payload))).hexdigest():
        raise Refusal("bootstrap payload digest disagrees with canonical bytes")
    return {
        "schema": SCHEMA,
        "kind": BOOTSTRAP_RECEIPT_KIND,
        "complete": True,
        "payload": {
            **dict(payload),
            "trusted_verifier": trusted_verifier,
            "protected_unchanged": protected,
            "phase_a_manifest": manifest,
            "phase_a_authority": authority,
            "old_verdict": dict(old_verdict),
            "old_hygiene_summary": dict(old_hygiene),
        },
        "payload_sha256": digest,
    }


def strict_load_manifest(path: Path, oid_len: int = 40) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Refusal(f"cannot read manifest: {exc}") from exc
    return parse_manifest(strict_loads(raw, what="manifest"), oid_len)


def strict_load_receipt(path: Path, oid_len: int = 40) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Refusal(f"cannot read protected transition receipt: {exc}") from exc
    return _parse_receipt(strict_loads(raw, what="receipt"), oid_len)


def strict_load_bootstrap_receipt(path: Path, oid_len: int = 40
                                  ) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Refusal(f"cannot read bootstrap receipt: {exc}") from exc
    return _parse_bootstrap_receipt(
        strict_loads(raw, what="bootstrap receipt"), oid_len)


def validate_bootstrap_binding(receipt: Mapping[str, Any], *,
                               trusted_base_commit: str,
                               trusted_base_tree: str,
                               phase_a_commit: str,
                               phase_a_tree: str) -> dict[str, str]:
    payload = receipt.get("payload")
    if not isinstance(payload, dict):
        raise Refusal("bootstrap receipt has no validated payload")
    expected = {
        "trusted_base_commit": trusted_base_commit,
        "trusted_base_tree": trusted_base_tree,
        "phase_a_commit": phase_a_commit,
        "phase_a_tree": phase_a_tree,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise Refusal("bootstrap receipt does not bind the requested base/Phase-A pair")
    return {
        "trusted_base_commit": trusted_base_commit,
        "phase_a_commit": phase_a_commit,
        "transition_manifest_sha256": payload["phase_a_manifest"]["sha256"],
        "receipt_sha256": hashlib.sha256(
            canonical_bytes(dict(receipt))).hexdigest(),
    }


def validate_receipt_binding(receipt: Mapping[str, Any], *, base_commit: str,
                             candidate_commit: str, base_tree: str,
                             candidate_tree: str) -> dict[str, str]:
    payload = receipt.get("payload")
    if not isinstance(payload, dict):
        raise Refusal("receipt has no validated payload")
    expected = {
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "base_tree": base_tree,
        "candidate_tree": candidate_tree,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise Refusal(f"receipt {key} does not bind the merge verdict")
    return {
        "operation": str(payload["operation"]),
        "base_transition_id": str(payload["base_transition_id"]),
        "candidate_transition_id": str(payload["candidate_transition_id"]),
        "base_current_state_id": str(payload["base_current_state_id"]),
        "base_next_state_id": str(payload["base_next_state_id"]),
        "base_state_id": str(payload["base_state_id"]),
        "candidate_state_id": str(payload["candidate_state_id"]),
        "receipt_sha256": hashlib.sha256(canonical_bytes(dict(receipt))).hexdigest(),
    }


def runtime_choice(receipt: Mapping[str, Any]) -> tuple[str, str]:
    """Return the one tuple whose bytes both differential arms must execute."""
    payload = receipt.get("payload")
    if not isinstance(payload, dict):
        raise Refusal("receipt has no validated payload")
    operation = payload.get("operation")
    if operation == "ACTIVATE":
        root = "candidate"
        state_id = payload.get("candidate_state_id")
    elif operation in {"STEADY", "PREPARE"}:
        root = "base"
        state_id = payload.get("base_state_id")
    else:
        raise Refusal("receipt has no executable protected runtime choice")
    return root, _state_id(state_id, "receipt runtime state id")


def require_semantic_runtime(receipt: Mapping[str, Any]) -> tuple[str, str]:
    """Select only the BASE-predeclared semantic runtime tuple.

    Phase A leaves the legacy runtime live.  The hermetic protocol is dormant
    until ACTIVATE selects BASE's complete `next` tuple; after activation an
    ordinary STEADY landing selects that same tuple.  Current/PREPARE refuses
    instead of feeding legacy, timeout-bearing bytes into a new protocol they
    cannot truthfully implement.
    """
    root, state_id = runtime_choice(receipt)
    payload = receipt.get("payload")
    if not isinstance(payload, dict):
        raise Refusal("receipt has no validated payload")
    next_id = _state_id(
        payload.get("base_next_state_id"), "receipt BASE next state id")
    if state_id != next_id:
        raise Refusal(
            "hermetic orchestration is dormant until the BASE-predeclared "
            "semantic runtime tuple is active")
    return root, state_id


def validate_verdict_record(value: Any, *, expected_base: str,
                            expected_head: str) -> dict[str, str]:
    """Recheck the embedded receipt before a recorded LAND_OK is reused."""
    if not isinstance(value, dict):
        raise Refusal("verdict record is not an object")
    required = {
        "verdict", "base_sha", "base_tree", "head_sha", "verified_sha",
        "verified_tree", "protected_landing_transition",
        "protected_transition_receipt",
    }
    if not required <= set(value):
        raise Refusal("verdict record omits protected transition binding")
    if value["verdict"] != "LAND_OK":
        raise Refusal("recorded verdict is not LAND_OK")
    if value["base_sha"] != expected_base or value["head_sha"] != expected_head:
        raise Refusal("recorded base/head does not match the reassert request")
    base = value["base_sha"]
    candidate = value["verified_sha"]
    base_tree = value["base_tree"]
    candidate_tree = value["verified_tree"]
    if not all(isinstance(item, str) for item in
               (base, candidate, base_tree, candidate_tree)):
        raise Refusal("verdict object bindings are not strings")
    oid_len = len(base)
    receipt = _parse_receipt(value["protected_transition_receipt"], oid_len)
    summary = validate_receipt_binding(
        receipt,
        base_commit=base,
        candidate_commit=candidate,
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )
    if value["protected_landing_transition"] != summary:
        raise Refusal("verdict protected transition summary disagrees with receipt")
    return summary


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temp, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short receipt write")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)
        os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--object-repo", type=Path, required=True)
    verify.add_argument("--base", required=True)
    verify.add_argument("--candidate", required=True)
    verify.add_argument("--candidate-gates", type=Path, required=True)
    verify.add_argument("--candidate-tests", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    reassert = sub.add_parser("validate-verdict")
    reassert.add_argument("--verdict", type=Path, required=True)
    reassert.add_argument("--expected-base", required=True)
    reassert.add_argument("--expected-head", required=True)
    select_runtime = sub.add_parser("select-runtime")
    select_runtime.add_argument("--receipt", type=Path, required=True)
    select_runtime.add_argument("--expected-base", required=True)
    select_runtime.add_argument("--expected-candidate", required=True)
    select_runtime.add_argument("--expected-base-tree", required=True)
    select_runtime.add_argument("--expected-candidate-tree", required=True)
    select_runtime.add_argument(
        "--require-semantic-runtime", action="store_true")
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--object-repo", type=Path, required=True)
    bootstrap.add_argument("--trusted-base", required=True)
    bootstrap.add_argument("--phase-a", required=True)
    bootstrap.add_argument("--old-verdict", type=Path, required=True)
    bootstrap.add_argument("--old-hygiene-summary", type=Path, required=True)
    bootstrap.add_argument("--receipt", type=Path, required=True)
    validate_bootstrap = sub.add_parser("validate-bootstrap")
    validate_bootstrap.add_argument("--receipt", type=Path, required=True)
    validate_bootstrap.add_argument("--expected-trusted-base", required=True)
    validate_bootstrap.add_argument("--expected-trusted-base-tree", required=True)
    validate_bootstrap.add_argument("--expected-phase-a", required=True)
    validate_bootstrap.add_argument("--expected-phase-a-tree", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "validate-verdict":
            raw = args.verdict.read_bytes()
            value = strict_loads(raw, what="verdict")
            summary = validate_verdict_record(
                value,
                expected_base=args.expected_base,
                expected_head=args.expected_head,
            )
            print("[PASS] protected landing verdict reassertion: "
                  f"{summary['operation']} {summary['receipt_sha256'][:12]}")
            return 0
        if args.command == "select-runtime":
            receipt = strict_load_receipt(
                args.receipt, oid_len=len(args.expected_base))
            validate_receipt_binding(
                receipt,
                base_commit=args.expected_base,
                candidate_commit=args.expected_candidate,
                base_tree=args.expected_base_tree,
                candidate_tree=args.expected_candidate_tree,
            )
            if args.require_semantic_runtime:
                root, state_id = require_semantic_runtime(receipt)
            else:
                root, state_id = runtime_choice(receipt)
            print(f"{root}\t{state_id}")
            return 0
        if args.command == "bootstrap":
            receipt = build_bootstrap_receipt(
                object_repo=args.object_repo,
                trusted_base=args.trusted_base,
                phase_a=args.phase_a,
                old_verdict=args.old_verdict,
                old_hygiene_summary=args.old_hygiene_summary,
            )
            _atomic_write(args.receipt, canonical_bytes(receipt))
            print("[PASS] protected landing bootstrap: old runtime unchanged; "
                  "future atomic tuple recorded")
            return 0
        if args.command == "validate-bootstrap":
            receipt = strict_load_bootstrap_receipt(
                args.receipt, oid_len=len(args.expected_trusted_base))
            summary = validate_bootstrap_binding(
                receipt,
                trusted_base_commit=args.expected_trusted_base,
                trusted_base_tree=args.expected_trusted_base_tree,
                phase_a_commit=args.expected_phase_a,
                phase_a_tree=args.expected_phase_a_tree,
            )
            print("[PASS] protected landing bootstrap receipt: "
                  f"{summary['receipt_sha256'][:12]}")
            return 0
        receipt = build_receipt(
            object_repo=args.object_repo,
            base=args.base,
            candidate=args.candidate,
            candidate_gates=args.candidate_gates,
            candidate_tests=args.candidate_tests,
        )
        _atomic_write(args.receipt, canonical_bytes(receipt))
    except (OSError, Refusal, subprocess.SubprocessError) as exc:
        print(f"[NORECORD] protected landing transition: {exc}", file=sys.stderr)
        return 2
    payload = receipt["payload"]
    print("[PASS] protected landing transition: "
          f"{payload['operation']} {payload['base_state_id']} -> "
          f"{payload['candidate_state_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
