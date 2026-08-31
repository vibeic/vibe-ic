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
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


SCHEMA = 1
MANIFEST_KIND = "vibeic.protected-landing-transition"
# A REGISTER MUST BE ABLE TO RECORD A CEREMONY THAT WAS SKIPPED.
#
# Every other shape here describes a MOVE, and `parse_manifest`, `classify_move`
# and the parity corpus each refuse a register that moves nothing -- "there is
# no settled manifest".  That is right for a transition and it left the register
# with no way back from the one thing it exists to catch.  MEASURED on
# `ac3232ddeb` (v1.14.4): `tools/ci/_gate_dispatch.sh` shipped bytes appearing in
# NEITHER recorded state, moved by `e37d10e1e7` (v1.14.3, which said in its own
# commit message that the file "needs a base-authorised PREPARE/ACTIVATE
# transition rather than an ordinary merge", and then landed as an ordinary
# push) and again by `ac3232ddeb`.  Re-observing the tree is the documented
# remedy, but a PREPARE has to authorise a move, and main had none pending: the
# last transition was fully activated.  So the remedy was unreachable until some
# unrelated protected file happened to need changing.
#
# A RE-OBSERVATION is that missing shape, and it is DECLARED, never inferred.
# It is not the historical malformation returning: those three manifests
# collapsed `current` onto `next` while still calling themselves transitions,
# and that is still refused, by the identical sentence, on the identical rule.
# What this adds is the OPPOSITE rule under a different `kind`:
#
#     transition      current.files MUST differ from next.files   (unchanged)
#     re-observation  current.files MUST EQUAL  next.files        (new)
#
# so neither kind can carry the other's shape, and a re-observation cannot
# smuggle an unannounced move any more than a transition can hide behind
# "nothing pending".  A re-observation authorises NOTHING, so under it every
# protected move by a candidate is undeclared and `classify_move` refuses it by
# name: the register is strictly STRICTER between transitions, not looser.
REOBSERVATION_KIND = "vibeic.protected-landing-reobservation"
MANIFEST_KINDS = frozenset({MANIFEST_KIND, REOBSERVATION_KIND})
RECEIPT_KIND = "vibeic.protected-landing-transition-receipt"
BOOTSTRAP_RECEIPT_KIND = "vibeic.protected-landing-bootstrap-receipt"
PUSH_PREFLIGHT_KIND = "vibeic.landing-push-preflight-receipt"
REBOUND_VERDICT_KIND = "vibeic.landing-verdict-rebind"
MANIFEST_PATH = "tools/ci/protected_landing_transition.json"
MAX_JSON_BYTES = 1024 * 1024
ROLE_VALUES = frozenset({"authority", "runtime"})
OPERATION_VALUES = frozenset({"STEADY", "PREPARE", "ACTIVATE", "RENAME"})
PUSH_PREFLIGHT_GATES = (
    "landing_collateral_revert_check.py",
    "commit_msg_nda_check.py",
    "nda_diff_scan_check.py",
    "git_prohibition_guard.py",
)
PUSH_PREFLIGHT_BASE_FILES = PUSH_PREFLIGHT_GATES + ("_commercial_pdk.py",)
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

#: THE RUNNER PROFILE, ONCE.  `_runner_profile` VALIDATES against this and
#: `protected_landing_manifest_author.render` BUILDS from it, so the register
#: cannot record a runner the verifier would reject -- and nobody has to keep a
#: second copy of it in a JSON file by hand.  It was a local literal inside the
#: validator, which meant the only way to author a manifest was to copy the
#: runner out of whatever manifest was already in the tree; that copy is how a
#: stale register stays stale.
RUNNER_PROFILE_ID = "vibeic-landing-hermetic-v1"
RUNNER_PROFILE_EXPECTED = {
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


def derived_runner() -> dict:
    """The runner row a manifest must carry, built from this file's own rules."""
    return {"schema": 1, "profile_id": RUNNER_PROFILE_ID, "engine": "docker",
            "image": RUNNER_IMAGE, **{k: (list(v) if isinstance(v, list) else v)
                                      for k, v in RUNNER_PROFILE_EXPECTED.items()}}


def derived_paths() -> list:
    """The protected SET, derived from what this verifier actually executes.

    THE REGISTER IS NOT A LIST SOMEBODY MAINTAINS.  Both roles are already
    declared in this file, because this file is the thing that enforces them:
    `RUNTIME_PATHS` is what a candidate may move under one authorised
    transition, `REQUIRED_AUTHORITY_PATHS` is what the verifier executes to
    reach a verdict.  The manifest used to carry a hand-kept copy of their
    union, and a copy of a rule is a rule that can drift from itself.

    MEASURED at v1.13.3, before this function existed: the manifest's 52 paths
    were EXACTLY this union -- 41 authority-only, 4 runtime-only, 7 both, zero
    surplus, zero missing.  So the copy was already redundant; it was only ever
    waiting to disagree.
    """
    rows = []
    for path in sorted(set(RUNTIME_PATHS) | set(REQUIRED_AUTHORITY_PATHS)):
        roles = []
        if path in REQUIRED_AUTHORITY_PATHS:
            roles.append("authority")
        if path in RUNTIME_PATHS:
            roles.append("runtime")
        rows.append({"path": path, "roles": roles})
    return rows


RUNTIME_PATHS = frozenset({
    "tools/gatekeeper-land.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/pytest_per_file_junit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_pytest_progress_plugin.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_watchdog.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_progress_run.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_census_freshness.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})

# This is the minimum trusted closure.  A manifest may name more imported
# modules, but it may not omit one of these and still call itself complete.
#
# AUTHORITY IS NOT RUNTIME, AND THE DIFFERENCE IS WHO MAY SUPPLY THE BYTES.
# `RUNTIME_PATHS` is compared for EXACT EQUALITY, because it is the set a
# candidate is ALLOWED to change under one authorised atomic transition — the
# landing runtime evolves, which is what PREPARE/ACTIVATE is for.  This set is
# compared as a SUBSET (`REQUIRED_AUTHORITY_PATHS <= authority`), because it is
# what the verifier EXECUTES TO REACH A VERDICT, and a candidate never supplies
# any of it at all.  A file that decides whether the candidate lands therefore
# belongs here and NOT in `RUNTIME_PATHS`: listing it there would hand the
# subject under test a sanctioned ACTIVATE channel over its own guard.
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
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_progress_run.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_corpus_location.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_crash_safe_scratch.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_gate_usage_exit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_vacuous_exit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_prose_polarity.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_routed_checker_progress.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/drc_vacuous_pass_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/hygiene_shard_plan.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/generated_test_list_min_guard.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_noop_verdict_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/macro_obs_geometry_intersect_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/policy_direction_pin_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_internal_fail_bubble_up_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_metrics.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_acceptance.json",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_gate.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_census_freshness.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})


class Refusal(RuntimeError):
    """The requested transition is not completely measured or authorised."""


class RebindMismatch(Refusal):
    """A measured identity mismatch: full verification is required."""


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


def _keys_with_optional(value: Any, keys: Iterable[str],
                       optional: Iterable[str], what: str) -> Mapping[str, Any]:
    """`_exact_keys`, plus keys a manifest MAY omit.

    A manifest written before an optional key existed must still parse, because
    BASE authority is read from whatever commit is the base -- including one
    older than the key.  Absent is not the same as malformed.
    """
    if not isinstance(value, dict):
        raise Refusal(f"{what} has the wrong schema: {type(value).__name__!r}")
    required, allowed = set(keys), set(keys) | set(optional)
    if not required <= set(value) or not set(value) <= allowed:
        raise Refusal(f"{what} has the wrong schema: {sorted(value)!r}")
    return value


def _move_row(value: Any, what: str) -> dict[str, str]:
    row = _exact_keys(value, {"from", "to"}, what)
    return {"from": _safe_path(row["from"], f"{what}.from"),
            "to": _safe_path(row["to"], f"{what}.to")}


def apply_moves(names: Sequence[str],
                moves: Sequence[Mapping[str, str]]) -> list[str]:
    """The protected path list AFTER the authorised renames, sorted.

    With no moves this returns `sorted(names)`, which for an already-sorted
    path list is `names` itself -- so every caller behaves exactly as it did
    before moves existed.  That identity is the negative control: a bug in the
    move code cannot reach a landing that declares no move.
    """
    renamed = {row["from"]: row["to"] for row in moves}
    return sorted(renamed.get(name, name) for name in names)


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
    expected = RUNNER_PROFILE_EXPECTED
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


def _parse_moves(value: Any, names: Sequence[str]) -> list[dict[str, str]]:
    """Validate the RENAMES this manifest authorises.

    WHY THIS EXISTS.  Before it, the protected register could evolve BYTES at
    frozen PATHS and nothing else: `build_receipt` observed the candidate at the
    BASE's path list, so a candidate that renamed a protected file refused with
    "protected path is absent" before a single test ran.  Adding, removing or
    renaming a protected runtime path was therefore inexpressible, and the only
    live precedent for doing it -- `c51f830824`, which grew `RUNTIME_PATHS` from
    nine entries to eleven -- says in its own last line that it "Landed with
    --no-verify".  A protocol whose only escape hatch is the bypass it exists to
    prevent is not enforcing anything; it is deferring the breakage.

    THE PROPERTY THAT MUST NOT BE WEAKENED, and is not: the candidate never
    supplies the policy it is judged by.  A move is authorised because the BASE
    manifest names it -- destination included -- and the candidate may only
    PERFORM the move BASE already declared.  `RUNTIME_PATHS` is still compared
    for exact equality against the CURRENT path set, from BASE's own code.

    An absent or empty `moves` makes every downstream computation identical to
    the pre-move behaviour.
    """
    if not isinstance(value, list):
        raise Refusal("manifest.moves is not a list")
    moves = [_move_row(row, f"manifest.moves[{index}]")
             for index, row in enumerate(value)]
    froms = [row["from"] for row in moves]
    if froms != sorted(froms) or len(froms) != len(set(froms)):
        raise Refusal("manifest.moves is not sorted and unique by `from`")
    tos = [row["to"] for row in moves]
    if len(tos) != len(set(tos)):
        raise Refusal("manifest.moves sends two paths to one destination")
    known = set(names)
    unknown = sorted(set(froms) - known)
    if unknown:
        raise Refusal("manifest.moves renames paths the register does not "
                      "protect: " + ", ".join(unknown))
    # A destination that is ALREADY protected would silently merge two rows
    # into one and drop a file from the register -- a deletion wearing a
    # rename's clothes, which is the exact failure this whole change is here
    # to make impossible.
    collide = sorted(set(tos) & known)
    if collide:
        raise Refusal("manifest.moves renames onto an already-protected path: "
                      + ", ".join(collide))
    if MANIFEST_PATH in tos:
        raise Refusal("manifest.moves cannot rename a path onto the manifest")
    return moves


def parse_manifest(value: Any, oid_len: int,
                   authorised_moves: Sequence[Mapping[str, str]] = ()
                   ) -> dict[str, Any]:
    """Parse and validate one transition manifest.

    `authorised_moves` is supplied ONLY when parsing a CANDIDATE manifest, and
    only from the BASE manifest's own `moves`.  A candidate that performs a
    base-authorised rename must ship a register protecting the MOVED path set,
    which by construction is not the base's `RUNTIME_PATHS` -- so without this
    the candidate's own register could never parse and the rename would be as
    inexpressible as it was before.

    Passing nothing restores the exact pre-move rule: the register must equal
    `RUNTIME_PATHS` on the nose.  Either way the candidate supplies no policy;
    it is measured against the base's set, or against the base's set with the
    base's own renames applied, and against nothing else.
    """
    root = _keys_with_optional(
        value,
        {"schema", "kind", "transition_id", "manifest_path", "runner", "paths",
         "current", "next"},
        {"moves"},
        "manifest",
    )
    if type(root["schema"]) is not int or root["schema"] != SCHEMA:
        raise Refusal("manifest.schema is not 1")
    if root["kind"] not in MANIFEST_KINDS:
        raise Refusal("manifest.kind is not a protected-landing register kind")
    reobservation = root["kind"] == REOBSERVATION_KIND
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
    moves = _parse_moves(root.get("moves", []), names)
    next_names = apply_moves(names, moves)
    role_map = {row["path"]: frozenset(row["roles"]) for row in paths}
    runtime = {path for path, roles in role_map.items() if "runtime" in roles}
    authority = {path for path, roles in role_map.items() if "authority" in roles}
    # The set this register must match: BASE's, or BASE's with BASE's own
    # authorised renames applied.  With no authorised moves the second is the
    # first, so this is the original single-set equality unchanged.
    expected_runtime = frozenset(
        apply_moves(sorted(RUNTIME_PATHS), authorised_moves))
    expected_authority = frozenset(
        apply_moves(sorted(REQUIRED_AUTHORITY_PATHS), authorised_moves))
    if runtime not in (RUNTIME_PATHS, expected_runtime):
        runtime_reference = expected_runtime
        # THE MESSAGE NAMES THE DIFFERENCE, NOT THE SIZE. It read "is not the
        # exact five-file tuple" while RUNTIME_PATHS held eleven — a sentence
        # that went stale the first time anyone protected another file and then
        # sent its reader looking for five. MEASURED 2026-08-28: the
        # timeout-as-verdict lane added `_progress_run.py` to RUNTIME_PATHS and
        # not to the manifest; this refusal fired for exactly the right reason
        # and described the wrong shape of problem, while fourteen cases of
        # `test_landing_gate_direct_push_tier` went red behind it on
        # `assert 2 == 1`.
        missing = sorted(runtime_reference - runtime)
        extra = sorted(runtime - runtime_reference)
        raise Refusal(
            "manifest runtime role set does not match RUNTIME_PATHS"
            + (f"; the manifest OMITS {missing}" if missing else "")
            + (f"; the manifest carries UNEXPECTED {extra}" if extra else ""))
    missing_authority = (REQUIRED_AUTHORITY_PATHS - authority
                         if REQUIRED_AUTHORITY_PATHS <= authority
                         or not authorised_moves
                         else expected_authority - authority)
    if missing_authority:
        raise Refusal("manifest omits trusted authority dependencies: "
                      + ", ".join(sorted(missing_authority)))
    current = _state(root["current"], oid_len, "manifest.current")
    next_state = _state(root["next"], oid_len, "manifest.next")
    if current["id"] == next_state["id"]:
        raise Refusal("manifest current and next state ids are equal")
    if [row["path"] for row in current["files"]] != names:
        raise Refusal("manifest.current does not exactly cover manifest.paths")
    # `next_names` IS `names` WHENEVER NO MOVE IS DECLARED, so the rule the
    # re-observation work landed at v1.14.7 -- next exactly covers the register
    # -- is preserved on the nose for every register that declares none.  A
    # register that DOES declare a rename covers the moved set instead, because
    # that is where its `next` bytes live.
    if [row["path"] for row in next_state["files"]] != next_names:
        raise Refusal(
            "manifest.next does not exactly cover manifest.paths"
            + (" after the authorised moves" if moves else ""))
    # A RE-OBSERVATION AUTHORISES NOTHING, SO IT CANNOT AUTHORISE A RENAME.
    # The two declarations are contradictory in the one direction that matters:
    # `moves` names a destination a candidate may move a protected path to, and
    # a register whose whole claim is "this records the tree and opens no
    # transition" must not be the thing that hands out that permission.  Refused
    # by name rather than left to fall out of the row comparison below, which
    # would have reported it as a smuggled byte change and sent its reader
    # looking in the wrong place.
    if reobservation and moves:
        raise Refusal("a re-observation records no move, so it cannot declare "
                      "one: " + ", ".join(row["from"] for row in moves))
    # THE TWO KINDS CARRY OPPOSITE RULES, AND BOTH ARE ENFORCED.
    #
    # The transition sentence is unchanged, on the unchanged predicate: a
    # register that calls itself a transition and moves nothing is the
    # malformation `1f1749d2d`, `b161ec6e5` and `eda53573f` shipped, and it
    # still cannot be parsed.  The re-observation sentence is its mirror: a
    # register that declares no move may not contain one, so the declaration
    # cannot be used as cover for bytes nobody authorised.
    if reobservation:
        smuggled = sorted(
            row["path"] for row, was in zip(next_state["files"],
                                            current["files"])
            if row != was)
        if smuggled:
            raise Refusal(
                "a re-observation records no move, but manifest next differs "
                "from current on: " + ", ".join(smuggled))
    elif current["files"] == next_state["files"]:
        raise Refusal("manifest next tuple does not differ from current")
    return {
        "schema": SCHEMA,
        "kind": root["kind"],
        "transition_id": transition_id,
        "manifest_path": MANIFEST_PATH,
        "runner": runner,
        "paths": paths,
        "moves": moves,
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


def _tree_delta_records(repo: Path, base_tree: str, candidate_tree: str,
                        oid_len: int) -> list[dict[str, str]]:
    """Canonical path/mode/blob identity of one final tree delta.

    Commit topology is deliberately absent.  `--no-renames` makes each record
    one path with one old/new mode and blob, and `-z` keeps every legal path
    unambiguous.  This is the functional identity a packaging-only rebind must
    preserve byte-for-byte.
    """
    raw = _git(
        repo,
        ["diff-tree", "--no-commit-id", "--raw", "-r", "-z",
         "--no-renames", base_tree, candidate_tree],
        binary=True,
    )
    assert isinstance(raw, bytes)
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise Refusal("canonical tree delta has a malformed raw record")
    records: list[dict[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            header = fields[index].decode("ascii", errors="strict")
            path = os.fsdecode(fields[index + 1])
            old_mode, new_mode, old_oid, new_oid, status = header[1:].split()
        except (UnicodeDecodeError, ValueError) as exc:
            raise Refusal("canonical tree delta record is malformed") from exc
        if not header.startswith(":") or status not in {"A", "D", "M", "T"}:
            raise Refusal("canonical tree delta uses an unsupported status")
        _safe_path(path, "canonical tree delta path")
        for oid, label in ((old_oid, "old blob"), (new_oid, "new blob")):
            if oid != "0" * oid_len:
                _oid(oid, oid_len, f"canonical tree delta {label}")
        for mode in (old_mode, new_mode):
            if mode not in {"000000", "100644", "100755", "120000"}:
                raise Refusal("canonical tree delta uses an unsupported mode")
        records.append({
            "path": path,
            "status": status,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "old_oid": old_oid,
            "new_oid": new_oid,
        })
    if [row["path"] for row in records] != sorted(
            {row["path"] for row in records}):
        raise Refusal("canonical tree delta paths are not sorted and unique")
    return records


def _tree_delta_sha256(records: Sequence[Mapping[str, str]]) -> str:
    return hashlib.sha256(canonical_bytes(list(records))).hexdigest()


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


def moved_paths(manifest: Mapping[str, Any]) -> list[str]:
    """The paths the two recorded states disagree on: the authorised move."""
    current = {row["path"]: row for row in manifest["current"]["files"]}
    return sorted(row["path"] for row in manifest["next"]["files"]
                  if current.get(row["path"]) != row)


def _rows_by_path(files: Sequence[Mapping[str, Any]], what: str
                  ) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in files:
        path = row["path"]
        if path in out:
            raise Refusal(f"{what} names {path} twice")
        out[path] = row
    return out


def classify_move(base_files: Sequence[Mapping[str, Any]],
                  candidate_files: Sequence[Mapping[str, Any]],
                  manifest: Mapping[str, Any]) -> tuple[str, str, str]:
    """Classify candidate-against-BASE as STEADY, ACTIVATE, or a named refusal.

    THE BASE IS OBSERVED, NEVER MATCHED.  This replaces `_match_state`, which
    asked whether the BASE's own protected tuple was byte-identical to one of
    two tuples recorded in the manifest, and refused the landing when it was
    not.  That question has a stale answer by construction: the recorded
    tuples photograph every protected path at one commit, so ANY later landing
    that moves ANY protected path -- including one no transition ever named --
    falsifies both of them, and every subsequent landing is refused for a
    change that is nobody's fault and that no re-render prevents recurring.

    MEASURED on `origin/main` while this was the rule: 60 of the last 60
    commits matched NEITHER of their own manifest's states, so `build_receipt`
    refused at its FIRST comparison for every candidate, and
    `test_phase_b_activated_parity.py` was red on trunk with three landings'
    worth of drift (`tools/gatekeeper-land.sh` at v1.13.8,
    `tools/ci/repo_hygiene_gates.sh` at v1.13.16,
    `ci_harness_timeout_ceiling_check.py`), none of them a defect and all of
    them staying.

    So the base's tuple is taken as GIVEN -- it is what this repository is --
    and the question becomes the one the register is actually for: WHAT DOES
    THE CANDIDATE MOVE, AND DID THE BASE AUTHORISE THAT MOVE.  Nothing is
    relaxed by this: the candidate is now compared against the base's OBSERVED
    bytes, which is strictly more accurate than comparing it against a
    photograph of some earlier commit, and every drifted path is NAMED.

      STEADY    the candidate moves no protected path at all.
      ACTIVATE  the candidate moves EXACTLY the paths the manifest's two
                states disagree on, to EXACTLY the bytes `next` records, and
                the base still stands at `current` on all of them.
      refusal   anything else, naming the paths -- a path the manifest
                authorises no move of, a half-applied activation, bytes other
                than the authorised ones, or a re-move of an already spent
                transition.

    `base_state_id` is still reported, because a receipt reader chooses the
    runtime by it: the base stands at `next` once the authorised move has been
    activated there, and at `current` until then.

    A RE-OBSERVATION register (`REOBSERVATION_KIND`) authorises no move at all.
    Under it the only classification reachable is STEADY, and every protected
    path a candidate touches is undeclared and refused by name -- so it is the
    strictest state this function has, not an escape from it.
    """
    names = [row["path"] for row in manifest["paths"]]
    base = _rows_by_path(base_files, "the base tuple")
    candidate = _rows_by_path(candidate_files, "the candidate tuple")
    current = _rows_by_path(manifest["current"]["files"], "manifest.current")
    nxt = _rows_by_path(manifest["next"]["files"], "manifest.next")
    for what, observed in (("base", base), ("candidate", candidate)):
        absent = sorted(set(names) - set(observed))
        if absent:
            raise Refusal(f"protected paths are absent from the {what}: "
                          + ", ".join(absent))

    moved = set(moved_paths(manifest))
    if not moved:
        # A RE-OBSERVATION AUTHORISES NOTHING, AND THAT IS THE STRICTER STATE.
        # `parse_manifest` has already refused an undeclared empty move, so
        # reaching here with `moved` empty means the register SAYS it records
        # the tree and opens no transition.  Every protected path is then
        # outside the authorised move, so any candidate that touches one falls
        # into `undeclared` below and is refused BY NAME -- the same refusal, on
        # a wider set.  Nothing can be activated under this register; the next
        # real move authors a PREPARE, which is the point.
        if manifest["kind"] != REOBSERVATION_KIND:
            raise Refusal(
                "the manifest authorises a transition that moves nothing")
        # Both states are the same bytes here, so either id names the live
        # state; `next` is chosen so a reader sees the id the register was
        # LAST re-observed under. Written out rather than left to `all(())`.
        base_state_id = manifest["next"]["id"]
    else:
        # Spent or pending, read off the BASE rather than asserted.
        activated_at_base = all(base[path] == nxt[path] for path in moved)
        base_state_id = (manifest["next"]["id"] if activated_at_base
                         else manifest["current"]["id"])

    drift = sorted(path for path in names if candidate[path] != base[path])
    if not drift:
        return "STEADY", base_state_id, base_state_id

    undeclared = [path for path in drift if path not in moved]
    if undeclared:
        # THE REMEDY IS PRINTED, not left to be remembered. The whole reason
        # this register went stale is that the obligation lived in somebody's
        # head; a refusal that names the file and hands back the exact command
        # that satisfies it does not.
        raise Refusal(
            "protected tuple matches neither authorised atomic state: the "
            "candidate moves protected paths the manifest authorises no move "
            "of: " + ", ".join(undeclared)
            + ". Declare the move in the same landing:  python3 tools/ci/"
            "protected_landing_manifest_author.py --commit <base> "
            "--transition-id <new-id> --current-id "
            + base_state_id + " --next-id <new-id>-next"
            + "".join(f" --next-file {path}={path}" for path in undeclared)
            + " --out " + MANIFEST_PATH)
    if moved and activated_at_base:
        raise Refusal(
            "protected tuple attempts a rollback or unprepared move: the "
            "authorised transition is already activated at the base, so a "
            "further move of these needs a new PREPARE: " + ", ".join(drift))
    wrong = sorted(path for path in moved if candidate[path] != nxt[path])
    if wrong:
        raise Refusal(
            "protected tuple matches neither authorised atomic state: the "
            "activation is partial, or installs bytes other than the ones "
            "`next` records, on: " + ", ".join(wrong))
    return "ACTIVATE", base_state_id, manifest["next"]["id"]


def classify_rename(base_files: Sequence[Mapping[str, Any]],
                    candidate_files: Sequence[Mapping[str, Any]],
                    base_manifest: Mapping[str, Any],
                    candidate_manifest: Mapping[str, Any]) -> tuple[str, str]:
    """Classify a candidate that PERFORMS the rename BASE authorised.

    A RENAME is the one operation that changes the protected PATH SET, and it
    is deliberately shaped so the register is never left mid-move:

      * BASE declares it.  `base_manifest["moves"]` names every `from` and
        every `to`.  The candidate supplies no policy; it performs one.
      * The candidate carries the `next` BYTES at the `to` PATHS, exactly.
      * The candidate RE-PHOTOGRAPHS the register in the same landing: its own
        manifest protects the moved path set, declares no further move, and
        stands at a fresh transition whose `current` is what the candidate
        actually holds.

    That last clause is why RENAME is not simply "ACTIVATE with paths".  An
    ACTIVATE keeps the manifest, so a path-moving ACTIVATE would leave the next
    base holding files its own register cannot name -- and `build_receipt`
    observes the base at its own register FIRST, so every later landing would
    refuse on the BASE, for a change that is nobody's fault.  That is precisely
    the deadlock `docs/research/2026-08-22-protected-tuple-unenforced-on-the-
    landing-path.md` measured, where three queued batches could not verify
    against main at all.  A move that cannot be completed in one landing must
    not be startable.

    Returns `(base_state_id, candidate_state_id)`.
    """
    moves = base_manifest["moves"]
    if not moves:
        raise Refusal("RENAME requires the base manifest to authorise a move")
    names = [row["path"] for row in base_manifest["paths"]]
    next_names = apply_moves(names, moves)

    base = _rows_by_path(base_files, "the base tuple")
    nxt = _rows_by_path(base_manifest["next"]["files"], "manifest.next")
    candidate = _rows_by_path(candidate_files, "the candidate tuple")

    absent = sorted(set(next_names) - set(candidate))
    if absent:
        raise Refusal("the candidate does not carry the renamed protected "
                      "paths: " + ", ".join(absent))

    # THE BASE MUST STILL STAND AT `current`.  A rename is spendable once.
    current = _rows_by_path(base_manifest["current"]["files"], "manifest.current")
    stale = sorted(path for path in names if base[path] != current[path])
    if stale:
        raise Refusal(
            "protected tuple matches neither authorised atomic state: the base "
            "has drifted from `current`, so the authorised rename is not the "
            "move it describes: " + ", ".join(stale))

    wrong = sorted(path for path in next_names if candidate[path] != nxt[path])
    if wrong:
        raise Refusal(
            "the rename is partial, or installs bytes other than the ones "
            "`next` records, on: " + ", ".join(wrong))

    # The candidate must close the transition rather than leave it open.
    cand_names = [row["path"] for row in candidate_manifest["paths"]]
    if cand_names != next_names:
        raise Refusal("the candidate register does not protect exactly the "
                      "moved path set")
    if candidate_manifest["moves"]:
        raise Refusal("the candidate register still declares a pending move")
    if candidate_manifest["transition_id"] == base_manifest["transition_id"]:
        raise Refusal("RENAME did not allocate a new transition id")
    if candidate_manifest["current"]["files"] != list(candidate_files):
        raise Refusal("the candidate register does not record the tuple the "
                      "candidate actually holds")
    return base_manifest["current"]["id"], candidate_manifest["current"]["id"]


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
    # The candidate's register is judged against BASE's set, or against BASE's
    # set with BASE's OWN authorised renames applied -- never against anything
    # the candidate itself declares.
    candidate_manifest = parse_manifest(
        strict_loads(cand_manifest_raw, what="candidate manifest"), oid_len,
        base_manifest["moves"])
    base_files = _observe_files(
        repo, base_commit, base_manifest["paths"], algorithm, oid_len)

    # THE CANDIDATE IS OBSERVED AT THE PATHS BASE AUTHORISED FOR IT.  With no
    # declared move that is the base's own path list, byte-for-byte the old
    # behaviour.  With one, it is the moved list -- and the only reason the
    # moved list may be trusted is that BASE, not the candidate, wrote it.
    rename_paths = None
    if base_manifest["moves"] and cand_manifest_raw != base_manifest_raw:
        rename_paths = [{"path": path, "roles": ["runtime"]}
                        for path in apply_moves(
                            [row["path"] for row in base_manifest["paths"]],
                            base_manifest["moves"])]
        try:
            candidate_files = _observe_files(
                repo, cand_commit, rename_paths, algorithm, oid_len)
        except Refusal:
            rename_paths = None
    if rename_paths is None:
        candidate_files = _observe_files(
            repo, cand_commit, base_manifest["paths"], algorithm, oid_len)

    if rename_paths is not None:
        operation = "RENAME"
        base_state_id, candidate_state_id = classify_rename(
            base_files, candidate_files, base_manifest, candidate_manifest)
    elif cand_manifest_raw == base_manifest_raw:
        operation, base_state_id, candidate_state_id = classify_move(
            base_files, candidate_files, base_manifest)
    else:
        operation = "PREPARE"
        # The base's own state id, observed. `classify_move` with the base as
        # its own candidate can only return STEADY, so this reads the id
        # without a second definition of how the id is decided.
        _steady, base_state_id, _same = classify_move(
            base_files, base_files, base_manifest)
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
    # Under RENAME the candidate stands at the moved paths, whose roles are the
    # roles of the paths they came FROM -- a rename may not launder a runtime
    # file into an authority one, or the reverse.
    cand_role_map = dict(role_map)
    for row in base_manifest["moves"]:
        cand_role_map[row["to"]] = role_map[row["from"]]
    base_observed = [{**row, "roles": role_map[row["path"]]}
                     for row in base_files]
    candidate_observed = [{**row, "roles": cand_role_map[row["path"]]}
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
        "moves": list(base_manifest["moves"]),
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


def _attestation_canonical_order(rows: Sequence[Any]) -> list[Any]:
    """Order a SET-like list totally, so hashing it is not hashing a race.

    `process_attestations` reaches this file in COMPLETION order.
    `_gate_dispatch.sh` appends one record per gate as that gate finishes, under
    a lock (`_gate_attest_locked`), and `gate_dispatch_finish` reads the file
    back without sorting (`:1604-1616`) -- so at any job count above one the
    order is whichever gate won the race.  `canonical_bytes` is
    `json.dumps(sort_keys=True)`, which sorts dict KEYS and never list ELEMENTS,
    so that race was being carried straight into
    `process_attestations_sha256`: measured 2026-08-31, two runs of the real
    dispatcher with the same two gates, the same argv and the same findings, the
    only difference being which finished first, produced
    `1e2aaa95...` and `c63951c6...`.

    ORDER WAS NEVER A PROPERTY OF THIS LIST, which is why sorting is the right
    repair rather than a papering-over.  Every consumer keys by label and
    requires exactly one record per label, in three independent places --
    `repo_hygiene_parallel.merge_records` ("expected one process attestation,
    got N"), `hygiene_finding_delta` (`Counter` bijection, then "not one"), and
    `gate_host_independence_check._load_checkout_attestations` ("duplicate
    process attestation").  Sorting by label is therefore a TOTAL order that no
    reader can distinguish from the one it was given.

    THE SIBLING `gates` IS DELIBERATELY NOT SORTED HERE.  Its order is
    declaration order, it is deterministic (`gate_dispatch_finish` drains the
    pool and replays in declaration order), and it is load-bearing --
    `merge_records` consumes it positionally with `zip(labels, gates)`.  Sorting
    that one would erase a real property instead of a race.

    The canonical bytes are the tiebreak so the key is total even for input this
    function is not entitled to assume well-formed; no new refusal is added,
    because a hash that starts refusing records the landing path accepts today
    is the same failure mode this repairs.
    """
    def key(row: Any) -> tuple[str, bytes]:
        label = row.get("label") if isinstance(row, dict) else None
        return (label if isinstance(label, str) else "", canonical_bytes(row))
    return sorted(rows, key=key)


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
        "process_attestations_sha256": hashlib.sha256(canonical_bytes(
            _attestation_canonical_order(
                value["process_attestations"]))).hexdigest(),
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
    payload = _keys_with_optional(
        root["payload"],
        {"operation", "base_commit", "base_tree", "candidate_commit",
         "candidate_tree", "base_manifest", "candidate_manifest",
         "runner",
         "base_transition_id", "candidate_transition_id",
         "base_current_state_id", "base_next_state_id", "base_state_id",
         "candidate_state_id", "base_files", "candidate_files", "worktrees"},
        {"moves"},
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
    moves = _parse_moves(payload.get("moves", []),
                         [row["path"] for row in base_files])
    base_paths = [row["path"] for row in base_files]
    candidate_paths = [row["path"] for row in candidate_files]
    # The candidate covers the base's path set, or -- only when the BASE
    # authorised a rename -- that set with the authorised renames applied.
    # `apply_moves` with no moves is the identity on a sorted list, so a
    # receipt that declares none is judged by exactly the old equality.
    expected_candidate_paths = apply_moves(base_paths, moves)
    if candidate_paths != expected_candidate_paths or not base_paths:
        raise Refusal("receipt protected tuples do not exact-cover one path set")
    role_map = {row["path"]: frozenset(row["roles"]) for row in base_files}
    # A renamed row keeps the roles of the path it came FROM.
    cand_role_map = dict(role_map)
    for row in moves:
        cand_role_map[row["to"]] = role_map[row["from"]]
    if any(frozenset(row["roles"]) != cand_role_map.get(row["path"])
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
    if operation == "RENAME" and not (
            moves and not same_files and not same_manifest
            and base_transition != candidate_transition
            and base_state == payload["base_current_state_id"]):
        raise Refusal(
            "RENAME receipt is not one base-authorised move that also closes "
            "the transition it spends")
    if operation != "RENAME" and moves and not same_manifest:
        # A base that has a pending rename and a candidate that rewrote the
        # manifest is a RENAME or it is nothing.  Refusing here stops a
        # candidate from spending the authorised destination under an
        # operation whose rules never look at it.
        raise Refusal(
            "the base authorises a pending rename, so a candidate that changes "
            "the manifest must be classified RENAME, not " + operation)
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


def _preflight_gate_record(name: str, proc: subprocess.CompletedProcess
                           ) -> dict[str, Any]:
    stdout = proc.stdout if isinstance(proc.stdout, bytes) else b""
    stderr = proc.stderr if isinstance(proc.stderr, bytes) else b""
    visible = stderr if proc.returncode else stdout
    lines = [line.strip() for line in
             visible.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    return {
        "name": name,
        "rc": proc.returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "summary": (lines[-1] if lines else "NO OUTPUT")[:1000],
    }


def build_push_preflight_receipt(*, object_repo: Path, base: str,
                                 candidate: str, push_range: str
                                 ) -> dict[str, Any]:
    """Run the cheap BASE-owned push gates before any expensive verifier arm.

    BLOCKING.  The programs are materialised from the immutable BASE commit,
    never imported from the candidate checkout.  A gate rc=1 is a measured
    REFUSE; rc=2/other is NORECORD.  Both stop the caller.
    """
    repo = object_repo.resolve(strict=True)
    algorithm, oid_len = _object_format(repo)
    del algorithm  # object width is the part this record needs
    base_commit, base_tree = _commit_and_tree(repo, base, oid_len, "base")
    candidate_commit, candidate_tree = _commit_and_tree(
        repo, candidate, oid_len, "candidate")
    if (not isinstance(push_range, str) or not push_range.strip()
            or "\n" in push_range or "\r" in push_range
            or len(push_range) > 4096):
        raise Refusal("push range is empty or not a safe one-line rev-list expression")
    parts = push_range.split()
    selected_raw = _git(repo, ["rev-list", *parts])
    assert isinstance(selected_raw, str)
    selected = selected_raw.split()
    if not selected or candidate_commit not in selected:
        raise Refusal("push range is empty or does not include the candidate")

    programs_rel = "vibe-ic-marketplace/plugins/vibe-ic/programs"
    gate_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="landing-push-preflight.") as temp:
        authority = Path(temp)
        for name in PUSH_PREFLIGHT_BASE_FILES:
            raw = _git(
                repo, ["show", f"{base_commit}:{programs_rel}/{name}"],
                binary=True)
            assert isinstance(raw, bytes)
            path = authority / name
            path.write_bytes(raw)
            path.chmod(0o500)
        env = _git_env()
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(authority)})

        commands: list[tuple[str, list[str]]] = [
            ("landing_collateral_revert_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
            ("commit_msg_nda_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
            ("nda_diff_scan_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
        ]
        for name, argv in commands:
            proc = _pr.run(
                [sys.executable, "-B", str(authority / name), *argv],
                env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
            gate_records.append(_preflight_gate_record(name, proc))

        messages = _git(
            repo, ["log", "--format=%B", *parts], binary=True)
        assert isinstance(messages, bytes)
        message_file = authority / "commit-messages.txt"
        message_file.write_bytes(messages)
        proc = _pr.run(
            [sys.executable, "-B", str(authority / "git_prohibition_guard.py"),
             str(message_file)],
            env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
        gate_records.append(_preflight_gate_record(
            "git_prohibition_guard.py", proc))

    if any(row["rc"] not in {0, 1} for row in gate_records):
        verdict = "NORECORD"
    elif any(row["rc"] == 1 for row in gate_records):
        verdict = "REFUSE"
    else:
        verdict = "PASS"
    payload = {
        "base_commit": base_commit,
        "base_tree": base_tree,
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "push_range": push_range,
        "gates": gate_records,
    }
    return {
        "schema": SCHEMA,
        "kind": PUSH_PREFLIGHT_KIND,
        "complete": verdict != "NORECORD",
        "verdict": verdict,
        "payload": payload,
        "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def parse_push_preflight_receipt(value: Any, oid_len: int) -> dict[str, Any]:
    root = _exact_keys(
        value,
        {"schema", "kind", "complete", "verdict", "payload",
         "payload_sha256"},
        "push preflight receipt")
    if type(root["schema"]) is not int or root["schema"] != SCHEMA:
        raise Refusal("push preflight receipt schema is not 1")
    if root["kind"] != PUSH_PREFLIGHT_KIND:
        raise Refusal("push preflight receipt has the wrong kind")
    if root["verdict"] not in {"PASS", "REFUSE", "NORECORD"}:
        raise Refusal("push preflight verdict is unknown")
    if root["complete"] is not (root["verdict"] != "NORECORD"):
        raise Refusal("push preflight completeness disagrees with its verdict")
    payload = _exact_keys(
        root["payload"],
        {"base_commit", "base_tree", "candidate_commit", "candidate_tree",
         "push_range", "gates"},
        "push preflight receipt.payload")
    for key in ("base_commit", "base_tree", "candidate_commit", "candidate_tree"):
        _oid(payload[key], oid_len, f"push preflight {key}")
    if (not isinstance(payload["push_range"], str)
            or not payload["push_range"].strip()
            or "\n" in payload["push_range"] or "\r" in payload["push_range"]):
        raise Refusal("push preflight range is malformed")
    gates = payload["gates"]
    if not isinstance(gates, list) or len(gates) != len(PUSH_PREFLIGHT_GATES):
        raise Refusal("push preflight does not exact-cover its gate set")
    parsed_gates = []
    for index, expected in enumerate(PUSH_PREFLIGHT_GATES):
        row = _exact_keys(
            gates[index],
            {"name", "rc", "stdout_sha256", "stderr_sha256", "summary"},
            f"push preflight gate[{index}]")
        if row["name"] != expected or type(row["rc"]) is not int:
            raise Refusal("push preflight gate order or rc is malformed")
        _sha256_value(row["stdout_sha256"], "push preflight stdout digest")
        _sha256_value(row["stderr_sha256"], "push preflight stderr digest")
        if not isinstance(row["summary"], str) or len(row["summary"]) > 1000:
            raise Refusal("push preflight gate summary is malformed")
        parsed_gates.append(dict(row))
    rcs = [row["rc"] for row in parsed_gates]
    expected_verdict = (
        "NORECORD" if any(rc not in {0, 1} for rc in rcs)
        else "REFUSE" if any(rc == 1 for rc in rcs)
        else "PASS")
    if root["verdict"] != expected_verdict:
        raise Refusal("push preflight verdict disagrees with its gate records")
    digest = root["payload_sha256"]
    _sha256_value(digest, "push preflight payload digest")
    canonical_payload = {**dict(payload), "gates": parsed_gates}
    if digest != hashlib.sha256(canonical_bytes(canonical_payload)).hexdigest():
        raise Refusal("push preflight payload digest disagrees with canonical bytes")
    return {
        "schema": SCHEMA,
        "kind": PUSH_PREFLIGHT_KIND,
        "complete": root["complete"],
        "verdict": root["verdict"],
        "payload": canonical_payload,
        "payload_sha256": digest,
    }


def validate_push_preflight_binding(receipt: Mapping[str, Any], *,
                                    base_commit: str,
                                    candidate_commit: str,
                                    base_tree: str,
                                    candidate_tree: str) -> dict[str, str]:
    if receipt.get("verdict") != "PASS" or receipt.get("complete") is not True:
        raise Refusal("push preflight did not record one complete PASS")
    payload = receipt.get("payload")
    if not isinstance(payload, dict):
        raise Refusal("push preflight receipt has no validated payload")
    expected = {
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "base_tree": base_tree,
        "candidate_tree": candidate_tree,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise Refusal("push preflight receipt does not bind the requested candidate")
    return {
        "push_range": str(payload["push_range"]),
        "payload_sha256": str(receipt["payload_sha256"]),
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


def _validate_original_verdict_record(value: Any, *, expected_base: str,
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


def build_rebound_verdict(*, object_repo: Path, base: str, candidate: str,
                          old_verdict: Path, push_preflight: Path,
                          protected_transition: Path) -> dict[str, Any]:
    """Rebind LAND_OK across a packaging-only one-commit rewrite.

    BLOCKING and deliberately narrow.  The base commit/tree, final candidate
    tree, canonical path/mode/blob delta, protected tuple, and cheap push gates
    must all be identical/green.  Any mismatch is a refusal to use this
    shortcut; the remedy is the normal full verifier.
    """
    repo = object_repo.resolve(strict=True)
    _algorithm, oid_len = _object_format(repo)
    base_commit, base_tree = _commit_and_tree(repo, base, oid_len, "base")
    candidate_commit, candidate_tree = _commit_and_tree(
        repo, candidate, oid_len, "candidate")
    parents_raw = _git(repo, ["rev-list", "--parents", "-n", "1",
                              candidate_commit])
    assert isinstance(parents_raw, str)
    parents = parents_raw.split()
    if len(parents) != 2 or parents[1] != base_commit:
        raise RebindMismatch(
            "rebind candidate is not exactly one commit parented on the verified base")

    try:
        old_value = strict_loads(old_verdict.read_bytes(), what="old verdict")
        preflight_value = strict_loads(
            push_preflight.read_bytes(), what="push preflight receipt")
        protected_value = strict_loads(
            protected_transition.read_bytes(),
            what="new protected transition receipt")
    except OSError as exc:
        raise Refusal(f"rebind evidence is unreadable: {exc}") from exc
    if not isinstance(old_value, dict) or old_value.get("kind") == REBOUND_VERDICT_KIND:
        raise Refusal("rebind source must be one original full-verifier verdict")
    old_head = old_value.get("head_sha")
    old_verified = old_value.get("verified_sha")
    old_tree = old_value.get("verified_tree")
    if not all(isinstance(item, str) for item in
               (old_head, old_verified, old_tree)):
        raise Refusal("old verdict omits commit/tree identity")
    _validate_original_verdict_record(
        old_value, expected_base=base_commit, expected_head=old_head)
    _old_verdict_binding(
        old_value,
        base_commit=base_commit,
        phase_commit=old_verified,
        phase_tree=old_tree,
        raw=canonical_bytes(old_value),
    )
    if old_value.get("base_tree") != base_tree:
        raise RebindMismatch(
            "old verdict base tree differs from the current verified base")
    if candidate_tree != old_tree:
        raise RebindMismatch(
            "candidate tree differs from the verified tree; run the full verifier")

    old_delta = _tree_delta_records(repo, base_tree, old_tree, oid_len)
    new_delta = _tree_delta_records(repo, base_tree, candidate_tree, oid_len)
    if not old_delta or old_delta != new_delta:
        raise RebindMismatch(
            "canonical path/mode/blob delta differs; run the full verifier")
    delta_sha = _tree_delta_sha256(old_delta)

    preflight_receipt = parse_push_preflight_receipt(
        preflight_value, oid_len)
    preflight_summary = validate_push_preflight_binding(
        preflight_receipt,
        base_commit=base_commit,
        candidate_commit=candidate_commit,
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )
    protected_receipt = _parse_receipt(protected_value, oid_len)
    protected_summary = validate_receipt_binding(
        protected_receipt,
        base_commit=base_commit,
        candidate_commit=candidate_commit,
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )
    body = {
        "schema": SCHEMA,
        "kind": REBOUND_VERDICT_KIND,
        "complete": True,
        "verdict": "LAND_OK",
        "unmeasurable": False,
        "base_sha": base_commit,
        "base_tree": base_tree,
        "head_sha": candidate_commit,
        "verified_sha": candidate_commit,
        "verified_tree": candidate_tree,
        "expected_tree": candidate_tree,
        "replayed_tree": candidate_tree,
        "rebase_status": "ok",
        "reasons": [],
        "candidate_run_truncated": False,
        "rebind": {
            "rebound_from_sha256": hashlib.sha256(
                canonical_bytes(old_value)).hexdigest(),
            "rebound_from_head_sha": old_head,
            "rebound_from_verified_sha": old_verified,
            "canonical_delta_sha256": delta_sha,
            "changed_paths": len(old_delta),
            "push_preflight": preflight_receipt,
            "push_preflight_summary": preflight_summary,
        },
        "rebound_from_verdict": old_value,
        "protected_landing_transition": protected_summary,
        "protected_transition_receipt": protected_receipt,
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(canonical_bytes(body)).hexdigest(),
    }


def _validate_rebound_verdict_record(value: Any, *, expected_base: str,
                                     expected_head: str,
                                     object_repo: Path | None) -> dict[str, str]:
    root = _exact_keys(
        value,
        {"schema", "kind", "complete", "verdict", "unmeasurable",
         "base_sha", "base_tree", "head_sha", "verified_sha",
         "verified_tree", "expected_tree", "replayed_tree", "rebase_status",
         "reasons", "candidate_run_truncated", "rebind",
         "rebound_from_verdict", "protected_landing_transition",
         "protected_transition_receipt", "receipt_sha256"},
        "rebound verdict")
    if (type(root["schema"]) is not int or root["schema"] != SCHEMA
            or root["kind"] != REBOUND_VERDICT_KIND
            or root["complete"] is not True
            or root["verdict"] != "LAND_OK"
            or root["unmeasurable"] is not False
            or root["reasons"] != []
            or root["candidate_run_truncated"] is not False
            or root["rebase_status"] != "ok"):
        raise Refusal("rebound verdict is not one complete LAND_OK record")
    if root["base_sha"] != expected_base or root["head_sha"] != expected_head:
        raise Refusal("rebound base/head does not match the reassert request")
    oid_len = len(expected_base)
    for key in ("base_sha", "base_tree", "head_sha", "verified_sha",
                "verified_tree", "expected_tree", "replayed_tree"):
        _oid(root[key], oid_len, f"rebound verdict {key}")
    if (root["head_sha"] != root["verified_sha"]
            or any(root[key] != root["verified_tree"] for key in
                   ("expected_tree", "replayed_tree"))):
        raise Refusal("rebound verdict does not exact-bind one final commit/tree")
    digest = root["receipt_sha256"]
    _sha256_value(digest, "rebound verdict digest")
    body = {key: value for key, value in root.items()
            if key != "receipt_sha256"}
    if digest != hashlib.sha256(canonical_bytes(body)).hexdigest():
        raise Refusal("rebound verdict digest disagrees with canonical bytes")

    rebind = _exact_keys(
        root["rebind"],
        {"rebound_from_sha256", "rebound_from_head_sha",
         "rebound_from_verified_sha", "canonical_delta_sha256",
         "changed_paths", "push_preflight", "push_preflight_summary"},
        "rebound verdict.rebind")
    for key in ("rebound_from_sha256", "canonical_delta_sha256"):
        _sha256_value(rebind[key], f"rebound {key}")
    for key in ("rebound_from_head_sha", "rebound_from_verified_sha"):
        _oid(rebind[key], oid_len, f"rebound {key}")
    if type(rebind["changed_paths"]) is not int or rebind["changed_paths"] <= 0:
        raise Refusal("rebound changed-path count is malformed")

    old = root["rebound_from_verdict"]
    if not isinstance(old, dict) or old.get("kind") == REBOUND_VERDICT_KIND:
        raise Refusal("rebound source is not an original full-verifier verdict")
    old_digest = hashlib.sha256(canonical_bytes(old)).hexdigest()
    if old_digest != rebind["rebound_from_sha256"]:
        raise Refusal("REBOUND_FROM digest disagrees with the embedded verdict")
    if (old.get("head_sha") != rebind["rebound_from_head_sha"]
            or old.get("verified_sha") != rebind["rebound_from_verified_sha"]
            or old.get("base_sha") != root["base_sha"]
            or old.get("base_tree") != root["base_tree"]
            or old.get("verified_tree") != root["verified_tree"]):
        raise Refusal("REBOUND_FROM identity differs from the new record")
    _validate_original_verdict_record(
        old, expected_base=root["base_sha"],
        expected_head=rebind["rebound_from_head_sha"])
    _old_verdict_binding(
        old,
        base_commit=root["base_sha"],
        phase_commit=rebind["rebound_from_verified_sha"],
        phase_tree=root["verified_tree"],
        raw=canonical_bytes(old),
    )

    preflight = parse_push_preflight_receipt(
        rebind["push_preflight"], oid_len)
    preflight_summary = validate_push_preflight_binding(
        preflight,
        base_commit=root["base_sha"],
        candidate_commit=root["head_sha"],
        base_tree=root["base_tree"],
        candidate_tree=root["verified_tree"],
    )
    if rebind["push_preflight_summary"] != preflight_summary:
        raise Refusal("rebound push-preflight summary disagrees with its receipt")
    protected_receipt = _parse_receipt(
        root["protected_transition_receipt"], oid_len)
    protected_summary = validate_receipt_binding(
        protected_receipt,
        base_commit=root["base_sha"],
        candidate_commit=root["head_sha"],
        base_tree=root["base_tree"],
        candidate_tree=root["verified_tree"],
    )
    if root["protected_landing_transition"] != protected_summary:
        raise Refusal("rebound protected transition summary disagrees with receipt")

    if object_repo is None:
        raise Refusal("rebound reassertion requires the object repository")
    repo = object_repo.resolve(strict=True)
    _algorithm, actual_oid_len = _object_format(repo)
    if actual_oid_len != oid_len:
        raise Refusal("rebound object format differs from the verdict")
    base_commit, base_tree = _commit_and_tree(
        repo, root["base_sha"], oid_len, "rebound base")
    head_commit, head_tree = _commit_and_tree(
        repo, root["head_sha"], oid_len, "rebound head")
    if (base_commit != root["base_sha"] or base_tree != root["base_tree"]
            or head_commit != root["head_sha"]
            or head_tree != root["verified_tree"]):
        raise Refusal("rebound object graph differs from the receipt")
    parents_raw = _git(repo, ["rev-list", "--parents", "-n", "1", head_commit])
    assert isinstance(parents_raw, str)
    parents = parents_raw.split()
    if len(parents) != 2 or parents[1] != base_commit:
        raise Refusal("rebound head is no longer one commit on the verified base")
    delta = _tree_delta_records(repo, base_tree, head_tree, oid_len)
    if (len(delta) != rebind["changed_paths"]
            or _tree_delta_sha256(delta) != rebind["canonical_delta_sha256"]):
        raise Refusal("rebound canonical path/mode/blob delta changed")
    return {
        "operation": "REBOUND",
        "receipt_sha256": digest,
        "rebound_from_sha256": old_digest,
    }


def validate_verdict_record(value: Any, *, expected_base: str,
                            expected_head: str,
                            object_repo: Path | None = None) -> dict[str, str]:
    """Reassert an original LAND_OK or a strict packaging-only rebound."""
    if isinstance(value, dict) and value.get("kind") == REBOUND_VERDICT_KIND:
        return _validate_rebound_verdict_record(
            value, expected_base=expected_base, expected_head=expected_head,
            object_repo=object_repo)
    return _validate_original_verdict_record(
        value, expected_base=expected_base, expected_head=expected_head)


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
    reassert.add_argument("--object-repo", type=Path)
    push_preflight = sub.add_parser("push-preflight")
    push_preflight.add_argument("--object-repo", type=Path, required=True)
    push_preflight.add_argument("--base", required=True)
    push_preflight.add_argument("--candidate", required=True)
    push_preflight.add_argument("--push-range", required=True)
    push_preflight.add_argument("--receipt", type=Path, required=True)
    rebind = sub.add_parser("rebind-verdict")
    rebind.add_argument("--object-repo", type=Path, required=True)
    rebind.add_argument("--base", required=True)
    rebind.add_argument("--candidate", required=True)
    rebind.add_argument("--old-verdict", type=Path, required=True)
    rebind.add_argument("--push-preflight", type=Path, required=True)
    rebind.add_argument("--protected-transition", type=Path, required=True)
    rebind.add_argument("--receipt", type=Path, required=True)
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
                object_repo=args.object_repo,
            )
            print("[PASS] protected landing verdict reassertion: "
                  f"{summary['operation']} {summary['receipt_sha256'][:12]}")
            return 0
        if args.command == "push-preflight":
            receipt = build_push_preflight_receipt(
                object_repo=args.object_repo,
                base=args.base,
                candidate=args.candidate,
                push_range=args.push_range,
            )
            _atomic_write(args.receipt, canonical_bytes(receipt))
            for gate in receipt["payload"]["gates"]:
                word = ("PASS" if gate["rc"] == 0 else
                        "FAIL" if gate["rc"] == 1 else "NORECORD")
                stream = sys.stdout if gate["rc"] == 0 else sys.stderr
                print(f"[{word}] {gate['name']}: {gate['summary']}", file=stream)
            verdict = receipt["verdict"]
            stream = sys.stdout if verdict == "PASS" else sys.stderr
            print(f"PUSH PREFLIGHT: {verdict} — "
                  f"{receipt['payload_sha256'][:12]}", file=stream)
            return 0 if verdict == "PASS" else 1 if verdict == "REFUSE" else 2
        if args.command == "rebind-verdict":
            try:
                receipt = build_rebound_verdict(
                    object_repo=args.object_repo,
                    base=args.base,
                    candidate=args.candidate,
                    old_verdict=args.old_verdict,
                    push_preflight=args.push_preflight,
                    protected_transition=args.protected_transition,
                )
            except RebindMismatch as exc:
                print(f"REBOUND: REFUSE — {exc}", file=sys.stderr)
                return 1
            _atomic_write(args.receipt, canonical_bytes(receipt))
            print("[PASS] landing verdict REBOUND_FROM "
                  f"{receipt['rebind']['rebound_from_sha256'][:12]} -> "
                  f"{receipt['head_sha'][:12]} tree "
                  f"{receipt['verified_tree'][:12]}")
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
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
