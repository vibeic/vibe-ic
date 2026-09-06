from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "protected_landing_transition", _HERE / "protected_landing_transition.py")
assert _SPEC and _SPEC.loader
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)
_RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "protected_runtime_snapshot", _HERE / "protected_runtime_snapshot.py")
assert _RUNTIME_SPEC and _RUNTIME_SPEC.loader
R = importlib.util.module_from_spec(_RUNTIME_SPEC)
_RUNTIME_SPEC.loader.exec_module(R)

_RUNNER = {
    "schema": 1,
    "profile_id": "vibeic-landing-hermetic-v1",
    "engine": "docker",
    "image": ("ghcr.io/vibeic/vibeic-eda@sha256:"
              "8da785a8d3275884ad0d0ee0fb10f7e90d8b7bf11a08d38e9559b0764112480f"),
    "platform": "linux/amd64",
    "user": "65534:65534",
    "network": "none",
    "read_only": True,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=536870912,mode=1777"],
    "pull": "never",
    "workdir": "/subject",
    "subject_mount": "read-only",
    "runtime_mount": "read-only",
    "corpus_mount": "read-only",
    "input_mounts": "selection-and-progress-plan-read-only",
    "runtime_overlays": "sorted-exact-files-read-only",
    "process_environment": "env-i-exact-arm-profile",
    "progress_protocol": "VIBEIC_PROGRESS/1",
    "evidence_transport": "private-volume-post-stop-export-and-absence-proof",
}


def test_manifest_and_runtime_use_one_exact_base_owned_image() -> None:
    runner_spec = importlib.util.spec_from_file_location(
        "_tested_hermetic_runner_profile", _HERE / "hermetic_candidate_runner.py")
    assert runner_spec and runner_spec.loader
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)
    assert P.RUNNER_IMAGE == runner.IMAGE == _RUNNER["image"]


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout.decode("ascii").strip()


def _write(repo: Path, rel: str, data: bytes, *, executable: bool = False) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if executable else 0o644)


def _record(repo: Path, rel: str, data: bytes | None = None) -> dict:
    path = repo / rel
    raw = path.read_bytes() if data is None else data
    oid = _git(repo, "hash-object", "--stdin", input_bytes=raw)
    executable = (path.stat().st_mode & 0o111) != 0
    return {
        "path": rel,
        "mode": "100755" if executable else "100644",
        "blob_oid": oid,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }


def _manifest(repo: Path, *, transition: str = "landing-semantic-v1",
              current_id: str = "legacy-timeout-v1",
              next_id: str = "semantic-progress-v1",
              current: list[dict] | None = None,
              next_files: list[dict] | None = None) -> dict:
    paths = sorted(P.REQUIRED_AUTHORITY_PATHS | P.RUNTIME_PATHS)
    role_rows = []
    for path in paths:
        roles = []
        if path in P.REQUIRED_AUTHORITY_PATHS:
            roles.append("authority")
        if path in P.RUNTIME_PATHS:
            roles.append("runtime")
        role_rows.append({"path": path, "roles": sorted(roles)})
    old = current or [_record(repo, path) for path in paths]
    if next_files is None:
        new = []
        for path in paths:
            raw = ((b"next:" + path.encode()) if path in P.RUNTIME_PATHS
                   else (repo / path).read_bytes())
            new.append(_record(repo, path, raw))
    else:
        new = next_files
    return {
        "schema": 1,
        "kind": P.MANIFEST_KIND,
        "transition_id": transition,
        "manifest_path": P.MANIFEST_PATH,
        "runner": dict(_RUNNER),
        "paths": role_rows,
        "current": {"id": current_id, "files": old},
        "next": {"id": next_id, "files": new},
    }


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str, dict]:
    repo = tmp_path / "object-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Transition Test")
    _git(repo, "config", "user.email", "transition@example.test")
    for rel in sorted(P.REQUIRED_AUTHORITY_PATHS | P.RUNTIME_PATHS):
        _write(
            repo, rel, b"old:" + rel.encode(),
            executable=rel in {"tools/gatekeeper-land.sh",
                               "tools/gatekeeper-verify-merge.sh"},
        )
    manifest = _manifest(repo)
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(manifest))
    base = _commit(repo, "base")
    return repo, base, manifest


def _worktrees(repo: Path, commit: str, tmp_path: Path) -> tuple[Path, Path]:
    gates = tmp_path / "candidate-gates"
    tests = tmp_path / "candidate-tests"
    _git(repo, "worktree", "add", "-q", "--detach", str(gates), commit)
    _git(repo, "worktree", "add", "-q", "--detach", str(tests), commit)
    return gates, tests


def _receipt(repo: Path, base: str, candidate: str, tmp_path: Path) -> dict:
    gates, tests = _worktrees(repo, candidate, tmp_path)
    return P.build_receipt(
        object_repo=repo, base=base, candidate=candidate,
        candidate_gates=gates, candidate_tests=tests)


def _base_runtime(repo: Path, base: str, tmp_path: Path) -> Path:
    runtime = tmp_path / "base-runtime"
    _git(repo, "worktree", "add", "-q", "--detach", str(runtime), base)
    return runtime


def _activate(repo: Path, manifest: dict, *, patch_one: bool = False) -> str:
    for row in manifest["next"]["files"]:
        if row["path"] not in P.RUNTIME_PATHS:
            continue
        raw = b"next:" + row["path"].encode()
        if patch_one and row["path"].endswith("ci_harness_timeout_ceiling_check.py"):
            raw += b"\nFAILED = 0\n"
        _write(
            repo, row["path"], raw,
            executable=row["mode"] == "100755")
    return _commit(repo, "candidate")


def test_steady_receipt_is_canonical_and_binds_both_worktrees(tmp_path):
    repo, base, _manifest_doc = _repo(tmp_path)
    _write(repo, "unrelated.txt", b"ordinary change")
    candidate = _commit(repo, "steady candidate")
    receipt = _receipt(repo, base, candidate, tmp_path)
    assert receipt["payload"]["operation"] == "STEADY"
    assert receipt["payload"]["base_state_id"] == "legacy-timeout-v1"
    assert [row["role"] for row in receipt["payload"]["worktrees"]] == [
        "candidate-gates", "candidate-tests"]
    path = tmp_path / "receipt.json"
    path.write_bytes(P.canonical_bytes(receipt))
    loaded = P.strict_load_receipt(path)
    assert loaded == receipt
    summary = P.validate_receipt_binding(
        loaded,
        base_commit=receipt["payload"]["base_commit"],
        candidate_commit=receipt["payload"]["candidate_commit"],
        base_tree=receipt["payload"]["base_tree"],
        candidate_tree=receipt["payload"]["candidate_tree"],
    )
    assert summary["operation"] == "STEADY"
    assert P.runtime_choice(loaded) == ("base", "legacy-timeout-v1")
    with pytest.raises(P.Refusal, match="dormant"):
        P.require_semantic_runtime(loaded)


def test_exact_atomic_next_tuple_is_the_only_activation(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    candidate = _activate(repo, manifest)
    receipt = _receipt(repo, base, candidate, tmp_path)
    payload = receipt["payload"]
    assert payload["operation"] == "ACTIVATE"
    assert payload["base_state_id"] == "legacy-timeout-v1"
    assert payload["candidate_state_id"] == "semantic-progress-v1"
    assert P.runtime_choice(receipt) == ("candidate", "semantic-progress-v1")
    assert P.require_semantic_runtime(receipt) == (
        "candidate", "semantic-progress-v1")


def test_steady_after_activation_uses_the_semantic_tuple(tmp_path):
    repo, _old_base, manifest = _repo(tmp_path)
    active_base = _activate(repo, manifest)
    _write(repo, "ordinary-after-activation.txt", b"ordinary\n")
    candidate = _commit(repo, "steady after activation")
    receipt = _receipt(repo, active_base, candidate, tmp_path)
    assert receipt["payload"]["operation"] == "STEADY"
    assert P.require_semantic_runtime(receipt) == (
        "base", "semantic-progress-v1")


def test_one_file_hybrid_is_refused(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    first = sorted(P.RUNTIME_PATHS)[0]
    row = next(item for item in manifest["next"]["files"]
               if item["path"] == first)
    _write(repo, first, b"next:" + first.encode(),
           executable=row["mode"] == "100755")
    candidate = _commit(repo, "hybrid")
    gates, tests = _worktrees(repo, candidate, tmp_path)
    with pytest.raises(P.Refusal, match="neither authorised atomic state"):
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)


def test_candidate_cannot_patch_checker_and_update_its_own_hash(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    _activate(repo, manifest, patch_one=True)
    # Launder the altered checker by changing candidate's own manifest next
    # tuple.  BASE still supplies the authority, so tuple+manifest in one
    # landing is PREPARE and PREPARE permits zero live-byte changes only.
    current = manifest["current"]["files"]
    observed_candidate = [
        _record(repo, path)
        for path in sorted(P.REQUIRED_AUTHORITY_PATHS | P.RUNTIME_PATHS)
    ]
    laundered = _manifest(
        repo, transition="candidate-self-hash", current=current,
        next_id="candidate-self-hash-next", next_files=observed_candidate)
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(laundered))
    candidate = _commit(repo, "self hash laundering")
    gates, tests = _worktrees(repo, candidate, tmp_path)
    with pytest.raises(P.Refusal, match="PREPARE changed live protected bytes"):
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)


def test_prepare_changes_only_future_authority_not_live_bytes(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    prepared = _manifest(
        repo,
        transition="landing-semantic-v2",
        current_id=manifest["current"]["id"],
        next_id="semantic-progress-v2",
        current=manifest["current"]["files"],
    )
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(prepared))
    candidate = _commit(repo, "prepare")
    receipt = _receipt(repo, base, candidate, tmp_path)
    assert receipt["payload"]["operation"] == "PREPARE"
    assert receipt["payload"]["base_files"] == receipt["payload"]["candidate_files"]
    assert receipt["payload"]["candidate_transition_id"] == "landing-semantic-v2"
    assert P.runtime_choice(receipt) == ("base", "legacy-timeout-v1")


def test_select_runtime_cli_revalidates_object_binding(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    candidate = _activate(repo, manifest)
    receipt = _receipt(repo, base, candidate, tmp_path)
    path = tmp_path / "receipt.json"
    path.write_bytes(P.canonical_bytes(receipt))
    payload = receipt["payload"]
    argv = [
        "python3", str(_HERE / "protected_landing_transition.py"),
        "select-runtime", "--receipt", str(path),
        "--expected-base", payload["base_commit"],
        "--expected-candidate", payload["candidate_commit"],
        "--expected-base-tree", payload["base_tree"],
        "--expected-candidate-tree", payload["candidate_tree"],
        "--require-semantic-runtime",
    ]
    selected = subprocess.run(argv, capture_output=True, text=True)
    assert selected.returncode == 0, selected.stdout + selected.stderr
    assert selected.stdout == "candidate\tsemantic-progress-v1\n"
    argv[-2] = "0" * 40
    refused = subprocess.run(argv, capture_output=True, text=True)
    assert refused.returncode == 2
    assert "does not bind" in refused.stderr


def test_prepare_cannot_change_path_roles_or_reuse_next_id(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    prepared = _manifest(
        repo,
        transition="landing-semantic-v2",
        current_id=manifest["current"]["id"],
        next_id=manifest["next"]["id"],
        current=manifest["current"]["files"],
    )
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(prepared))
    candidate = _commit(repo, "reuse")
    gates, tests = _worktrees(repo, candidate, tmp_path)
    with pytest.raises(P.Refusal, match="new next state id"):
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)


def test_prepare_cannot_replace_the_base_owned_runner_digest(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    prepared = _manifest(
        repo,
        transition="landing-semantic-v2",
        current_id=manifest["current"]["id"],
        next_id="semantic-progress-v2",
        current=manifest["current"]["files"],
    )
    prepared["runner"]["image"] = (
        "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64)
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(prepared))
    candidate = _commit(repo, "runner self-authority")
    gates, tests = _worktrees(repo, candidate, tmp_path)
    with pytest.raises(P.Refusal, match="BASE-owned runner image"):
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)


def test_worktree_untracked_or_raw_byte_mutation_is_refused(tmp_path):
    repo, base, _manifest_doc = _repo(tmp_path)
    candidate = base
    gates, tests = _worktrees(repo, candidate, tmp_path)
    (gates / "untracked-laundering.py").write_text("pass\n")
    with pytest.raises(P.Refusal, match="worktree raw attestation failed"):
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)


@pytest.mark.parametrize("bad", [
    b'{"schema":1,"schema":1}',
    b'{"schema":NaN}',
    b'\xff',
])
def test_strict_json_refuses_duplicate_nonfinite_and_non_utf8(bad):
    with pytest.raises(P.Refusal):
        P.strict_loads(bad, what="adversarial")


def test_runner_requires_digest_and_exact_hermetic_profile(tmp_path):
    repo, _base, manifest = _repo(tmp_path)
    for field, value in (("image", "ghcr.io/vibeic/vibeic-eda:latest"),
                         ("network", "bridge"),
                         ("read_only", False),
                         ("user", "0:0")):
        bad = json.loads(json.dumps(manifest))
        bad["runner"][field] = value
        with pytest.raises(P.Refusal, match="runner"):
            P.parse_manifest(bad, 40)


def test_receipt_bool_int_extra_key_and_digest_tamper_are_refused(tmp_path):
    repo, base, _manifest_doc = _repo(tmp_path)
    receipt = _receipt(repo, base, base, tmp_path)
    for mutate in ("bool", "extra", "digest"):
        bad = json.loads(json.dumps(receipt))
        if mutate == "bool":
            bad["schema"] = True
        elif mutate == "extra":
            bad["payload"]["worktrees"][0]["candidate_owned"] = True
            bad["payload_sha256"] = hashlib.sha256(
                P.canonical_bytes(bad["payload"])).hexdigest()
        else:
            bad["payload_sha256"] = "0" * 64
        path = tmp_path / f"bad-{mutate}.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(P.Refusal):
            P.strict_load_receipt(path)


def test_runtime_snapshot_uses_base_tree_plus_exact_activated_tuple(tmp_path):
    repo, base, manifest = _repo(tmp_path)
    _write(repo, "ordinary-subject.py", b"BASE\n")
    base = _commit(repo, "base with ordinary subject")
    # Rebind the manifest current observations after adding the ordinary file;
    # protected bytes themselves did not move.
    candidate = _activate(repo, manifest)
    _write(repo, "ordinary-subject.py", b"CANDIDATE MUST NOT BE RUNTIME\n")
    candidate = _commit(repo, "candidate ordinary change")
    receipt = _receipt(repo, base, candidate, tmp_path)
    base_runtime = _base_runtime(repo, base, tmp_path)
    output = tmp_path / "sealed-runtime"
    record = R.materialize(
        object_repo=repo, receipt=receipt, base_snapshot=base_runtime,
        output=output)
    assert record["payload"]["operation"] == "ACTIVATE"
    assert (output / "ordinary-subject.py").read_bytes() == b"BASE\n"
    for row in manifest["next"]["files"]:
        if row["path"] in P.RUNTIME_PATHS:
            assert (output / row["path"]).read_bytes() == \
                b"next:" + row["path"].encode()
    assert R.validate(
        object_repo=repo, receipt=receipt, snapshot=output) == record


def test_runtime_snapshot_post_validation_refuses_mutation(tmp_path):
    repo, base, _manifest_doc = _repo(tmp_path)
    receipt = _receipt(repo, base, base, tmp_path)
    base_runtime = _base_runtime(repo, base, tmp_path)
    output = tmp_path / "sealed-runtime"
    R.materialize(
        object_repo=repo, receipt=receipt, base_snapshot=base_runtime,
        output=output)
    victim = output / sorted(P.RUNTIME_PATHS)[0]
    victim.write_bytes(b"restored-looking but different runtime\n")
    with pytest.raises(R.Refusal, match="raw-byte attestation failed"):
        R.validate(object_repo=repo, receipt=receipt, snapshot=output)


def test_runtime_snapshot_accepts_exact_plain_base_archive(tmp_path):
    repo, base, _manifest_doc = _repo(tmp_path)
    receipt = _receipt(repo, base, base, tmp_path)
    linked = _base_runtime(repo, base, tmp_path)
    plain = tmp_path / "plain-base-runtime"
    shutil.copytree(linked, plain, ignore=shutil.ignore_patterns(".git"))
    output = tmp_path / "sealed-plain-runtime"
    record = R.materialize(
        object_repo=repo, receipt=receipt, base_snapshot=plain, output=output)
    assert record["payload"]["base_commit"] == base
    assert not (output / ".git").exists()
    assert output.stat().st_mode & 0o777 == 0o755


def _bootstrap_repo(tmp_path: Path, *, change_runtime: bool = False):
    repo = tmp_path / "bootstrap-object-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Bootstrap Test")
    _git(repo, "config", "user.email", "bootstrap@example.test")
    # The old base predates the manifest/validator but owns the five live
    # runtime files and the verifier which produced the external LAND_OK.
    for rel in sorted(P.RUNTIME_PATHS | {"tools/gatekeeper-verify-merge.sh"}):
        _write(repo, rel, b"old:" + rel.encode(),
               executable=rel in {"tools/gatekeeper-land.sh",
                                  "tools/gatekeeper-verify-merge.sh"})
    base = _commit(repo, "trusted old base")
    for rel in sorted(P.REQUIRED_AUTHORITY_PATHS | P.RUNTIME_PATHS):
        if not (repo / rel).exists():
            _write(repo, rel, b"phase-a:" + rel.encode())
    if change_runtime:
        rel = "tools/gatekeeper-land.sh"
        _write(repo, rel, b"candidate changed live gate", executable=True)
    manifest = _manifest(repo)
    _write(repo, P.MANIFEST_PATH, P.canonical_bytes(manifest))
    phase_a = _commit(repo, "phase A")
    phase_tree = _git(repo, "rev-parse", f"{phase_a}^{{tree}}")
    verdict = tmp_path / "old-verdict.json"
    verdict.write_text(json.dumps({
        "verdict": "LAND_OK", "base_sha": base,
        "head_sha": phase_a,
        "verified_sha": phase_a, "verified_tree": phase_tree,
        "expected_tree": phase_tree, "replayed_tree": phase_tree,
        "rebase_status": "ok", "reasons": [], "unmeasurable": False,
        "candidate_run_truncated": False, "verification_tier": "merge-tree",
        "land": {"pass": ["fixture"], "fail": [], "skip": [], "report": []},
        "delta": {"new_failures": [], "silenced": [], "weakened": []},
    }) + "\n")
    hygiene = tmp_path / "old-hygiene.json"
    label = 'corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it'
    hygiene.write_text(json.dumps({
        "declared": 1, "ran": 1, "decided": 0, "passed": 0,
        "failed": 0, "not_checked": 1, "wrote_corpus": 0,
        "deferred": 0, "other_shard": 0, "out_of_scope": 0,
        "gates": [{"label": label, "state": "NOT_CHECKED"}],
        "corpora": [{"name": "published cells carrying a routed DEF",
                     "items": 0, "gates": 1, "expansion": "EXPANDED"}],
        "process_attestations": [], "not_checked_unexempted": [label],
        "wiring_errors": [], "undisclosed_loops": [],
        "exemptions_expired": [], "listed_only": False, "shard": None,
        "corpus_inputs": {"benchmark_data_sha": None},
    }, sort_keys=True) + "\n")
    return repo, base, phase_a, verdict, hygiene


def test_one_time_bootstrap_binds_old_verdict_and_unchanged_runtime(tmp_path):
    repo, base, phase_a, verdict, hygiene = _bootstrap_repo(tmp_path)
    receipt = P.build_bootstrap_receipt(
        object_repo=repo, trusted_base=base, phase_a=phase_a,
        old_verdict=verdict, old_hygiene_summary=hygiene)
    assert receipt["kind"] == P.BOOTSTRAP_RECEIPT_KIND
    payload = receipt["payload"]
    assert payload["land_verdict"] == "LAND_OK"
    assert len(payload["protected_unchanged"]) == len(P.RUNTIME_PATHS)
    assert {row["path"] for row in payload["phase_a_authority"]} \
        >= P.REQUIRED_AUTHORITY_PATHS
    assert payload["trusted_verifier"]["path"] == \
        "tools/gatekeeper-verify-merge.sh"
    receipt_path = tmp_path / "bootstrap-receipt.json"
    receipt_path.write_bytes(P.canonical_bytes(receipt))
    parsed = P.strict_load_bootstrap_receipt(receipt_path)
    summary = P.validate_bootstrap_binding(
        parsed,
        trusted_base_commit=payload["trusted_base_commit"],
        trusted_base_tree=payload["trusted_base_tree"],
        phase_a_commit=payload["phase_a_commit"],
        phase_a_tree=payload["phase_a_tree"],
    )
    assert summary["phase_a_commit"] == phase_a


def test_bootstrap_refuses_partial_old_verdict_or_hygiene(tmp_path):
    repo, base, phase_a, verdict, hygiene = _bootstrap_repo(tmp_path)
    verdict.write_text(json.dumps({
        "verdict": "LAND_OK", "base_sha": base,
        "verified_sha": phase_a,
        "verified_tree": _git(repo, "rev-parse", f"{phase_a}^{{tree}}"),
    }) + "\n")
    with pytest.raises(P.Refusal, match="verdict is partial"):
        P.build_bootstrap_receipt(
            object_repo=repo, trusted_base=base, phase_a=phase_a,
            old_verdict=verdict, old_hygiene_summary=hygiene)
    second = tmp_path / "second"
    second.mkdir()
    _repo2, base2, phase2, verdict2, hygiene2 = _bootstrap_repo(second)
    hygiene2.write_text("{}\n")
    with pytest.raises(P.Refusal, match="hygiene summary is partial"):
        P.build_bootstrap_receipt(
            object_repo=_repo2, trusted_base=base2, phase_a=phase2,
            old_verdict=verdict2, old_hygiene_summary=hygiene2)


def test_bootstrap_candidate_manifest_cannot_authorize_a_live_change(tmp_path):
    repo, base, phase_a, verdict, hygiene = _bootstrap_repo(
        tmp_path, change_runtime=True)
    with pytest.raises(P.Refusal, match="changed protected runtime bytes"):
        P.build_bootstrap_receipt(
            object_repo=repo, trusted_base=base, phase_a=phase_a,
            old_verdict=verdict, old_hygiene_summary=hygiene)


# ---------------------------------------------------------------------------
# THE BASE IS OBSERVED, NOT MATCHED -- and that must not disarm the guard.
#
# `_match_state` used to be asked about the BASE's own tuple, which made every
# landing on a trunk that had legitimately moved ANY protected path refuse at
# `build_receipt`'s first comparison, and put `test_phase_b_activated_parity`
# red on trunk. MEASURED at v1.13.21: three landings (v1.13.8
# `tools/gatekeeper-land.sh`, v1.13.16 `tools/ci/repo_hygiene_gates.sh`, and
# `ci_harness_timeout_ceiling_check.py`) had drifted the tuple, all of them
# legitimate and all of them staying.
#
# These two are a matched pair on ONE drifted base: the first requires that a
# drifted base no longer deadlocks, the second requires that the SAME base
# still refuses a candidate that moves the SAME path -- by name. Without the
# second, the first is just an exemption.
# ---------------------------------------------------------------------------

def _drifted_base(repo: Path, tmp_path: Path) -> tuple[str, str]:
    """An ordinary landing that moved a protected path no transition names."""
    victim = sorted(P.REQUIRED_AUTHORITY_PATHS - P.RUNTIME_PATHS)[0]
    _write(repo, victim, b"landed-on-trunk:" + victim.encode())
    return _commit(repo, "an ordinary landing that moves a protected path"), victim


def test_a_base_that_drifted_on_an_unauthorised_path_no_longer_deadlocks(tmp_path):
    repo, _first_base, _manifest_doc = _repo(tmp_path)
    base, victim = _drifted_base(repo, tmp_path)
    _write(repo, "unrelated.txt", b"ordinary change")
    candidate = _commit(repo, "steady candidate on a drifted base")
    receipt = _receipt(repo, base, candidate, tmp_path)
    assert receipt["payload"]["operation"] == "STEADY"
    assert receipt["payload"]["base_state_id"] == "legacy-timeout-v1"
    # THE DRIFT IS WITNESSED, not assumed: the base's own manifest still
    # records the pre-drift bytes for `victim`, so the old `_match_state(base)`
    # comparison is exactly the one that would have refused here.
    recorded_raw = _git(repo, "show", f"{base}:{P.MANIFEST_PATH}")
    recorded = {row["path"]: row
                for row in json.loads(recorded_raw)["current"]["files"]}
    observed = {row["path"]: row for row in receipt["payload"]["base_files"]}
    assert observed[victim]["sha256"] != recorded[victim]["sha256"], (
        "the base did not actually drift, so this proves nothing")
    assert P.moved_paths(json.loads(recorded_raw)) == sorted(P.RUNTIME_PATHS), (
        "`victim` is inside the authorised move, so it is not undeclared")
    assert victim not in P.moved_paths(json.loads(recorded_raw))


def test_the_drifted_base_still_refuses_a_candidate_that_moves_that_path(tmp_path):
    repo, _first_base, _manifest_doc = _repo(tmp_path)
    base, victim = _drifted_base(repo, tmp_path)
    _write(repo, victim, b"and now the candidate edits it too")
    candidate = _commit(repo, "undeclared move of a protected path")
    gates, tests = _worktrees(repo, candidate, tmp_path)
    with pytest.raises(P.Refusal, match="neither authorised atomic state") as caught:
        P.build_receipt(
            object_repo=repo, base=base, candidate=candidate,
            candidate_gates=gates, candidate_tests=tests)
    assert victim in str(caught.value), str(caught.value)


def test_the_authorised_activation_still_lands_on_a_drifted_base(tmp_path):
    """The control for the pair above: the guard says YES to the real move.

    A refusal that fires on everything is not discriminating, so the drifted
    base must still ACTIVATE the transition the manifest actually authorises.
    """
    repo, _first_base, manifest = _repo(tmp_path)
    base, _victim = _drifted_base(repo, tmp_path)
    candidate = _activate(repo, manifest)
    receipt = _receipt(repo, base, candidate, tmp_path)
    assert receipt["payload"]["operation"] == "ACTIVATE"
    assert receipt["payload"]["candidate_state_id"] == "semantic-progress-v1"


def _hygiene_doc(attestations):
    """One structurally complete hygiene summary over two green gates."""
    return {
        "declared": 2, "ran": 2, "decided": 2, "passed": 2, "failed": 0,
        "not_checked": 0, "wrote_corpus": 0, "deferred": 0, "other_shard": 0,
        "out_of_scope": 0,
        "gates": [{"label": "alpha gate", "state": "PASS"},
                  {"label": "beta gate", "state": "PASS"}],
        "corpora": [], "process_attestations": list(attestations),
        "not_checked_unexempted": [], "wiring_errors": [],
        "undisclosed_loops": [], "exemptions_expired": [],
        "listed_only": False, "shard": None,
        "corpus_inputs": {"benchmark_data_sha": None},
    }


_ALPHA = {"schema": 1, "complete": True, "label": "alpha gate", "state": "PASS",
          "argv_sha256": "a" * 64, "returncode": 0,
          "verdict_line": "[PASS] 1 item", "finding_identities": [],
          "semantic_sha256": "b" * 64}
_BETA = {"schema": 1, "complete": True, "label": "beta gate", "state": "PASS",
         "argv_sha256": "c" * 64, "returncode": 0,
         "verdict_line": "[PASS] 1 item", "finding_identities": [],
         "semantic_sha256": "d" * 64}


def _attestation_digest(rows):
    doc = _hygiene_doc(rows)
    raw = (json.dumps(doc, sort_keys=True) + "\n").encode("utf-8")
    return P._old_hygiene_binding(doc, raw=raw)["process_attestations_sha256"]


def test_attestation_digest_does_not_record_which_gate_won_the_race():
    """The hash must identify the evidence, not the order it arrived in.

    `_gate_dispatch.sh` appends one attestation per gate AS THAT GATE FINISHES,
    under a lock, and `gate_dispatch_finish` reads the file back without
    sorting, so above one job the list order is whichever gate won.
    `canonical_bytes` is `json.dumps(sort_keys=True)`, which sorts dict KEYS and
    never list ELEMENTS -- so before the repair the same run, the same gates and
    the same findings hashed two different ways depending on the race.

    NEGATIVE CONTROL, in the same test, so a future edit that deletes the
    canonicalisation cannot leave this passing: the pre-repair formula is
    computed inline and asserted to be the thing that DID differ.
    """
    forward = _attestation_digest([_ALPHA, _BETA])
    reverse = _attestation_digest([_BETA, _ALPHA])
    assert forward == reverse, (
        "process_attestations_sha256 still carries the completion order")

    pre_fix_forward = hashlib.sha256(
        P.canonical_bytes([_ALPHA, _BETA])).hexdigest()
    pre_fix_reverse = hashlib.sha256(
        P.canonical_bytes([_BETA, _ALPHA])).hexdigest()
    assert pre_fix_forward != pre_fix_reverse, (
        "the negative control is vacuous: the unsorted formula no longer "
        "distinguishes these two orders, so this test proves nothing")


def test_attestation_digest_still_moves_when_the_evidence_moves():
    """Anti-cheat: canonicalising the ORDER must not blind the hash to CONTENT.

    `return []` and `return [row["label"] for row in rows]` both make the test
    above pass.  Neither may make this one pass.
    """
    baseline = _attestation_digest([_ALPHA, _BETA])
    red = dict(_BETA, returncode=1, state="FAIL",
               verdict_line="[FAIL] named-red",
               finding_identities=["[FAIL] named-red"])
    assert _attestation_digest([_ALPHA, red]) != baseline
    assert _attestation_digest([_ALPHA]) != baseline
    dup = _attestation_digest([_ALPHA, _BETA, _BETA])
    assert dup != baseline, (
        "a duplicated attestation was silently collapsed by the ordering")


def test_gate_digest_is_deliberately_left_order_sensitive():
    """The sibling is NOT the same defect and must not be 'fixed' alongside it.

    `gates` reaches this file in DECLARATION order -- deterministic, and
    load-bearing: `repo_hygiene_parallel.merge_records` consumes it positionally
    with `zip(labels, gates)`.  Sorting it would erase a real property rather
    than a race, so its digest is expected to distinguish two orders.
    """
    def digest(gates):
        doc = _hygiene_doc([_ALPHA, _BETA])
        doc["gates"] = gates
        raw = (json.dumps(doc, sort_keys=True) + "\n").encode("utf-8")
        return P._old_hygiene_binding(doc, raw=raw)["gates_sha256"]

    forward = [{"label": "alpha gate", "state": "PASS"},
               {"label": "beta gate", "state": "PASS"}]
    assert digest(forward) != digest(list(reversed(forward)))


# ---------------------------------------------------------------------------
# THE RE-OBSERVATION SHAPE.
#
# A register must be able to record a ceremony that was SKIPPED. Every other
# shape here describes a move, and a manifest that moves nothing is refused --
# correctly, for a transition. MEASURED on `ac3232ddeb` (v1.14.4):
# `tools/ci/_gate_dispatch.sh` shipped bytes in NEITHER recorded state, moved by
# `e37d10e1e7` (v1.14.3) and again by `ac3232ddeb`, neither under a transition;
# and the documented remedy -- re-author at the current base -- needs a PREPARE,
# which needs a move, and main had none pending.
#
# These four cases are the bidirectional control: the new shape is ACCEPTED and
# is STRICTER, the new way to lie is REFUSED, and the old refusal is proven
# still live on the identical predicate. A shape that only ever sees the input
# that passes has not been checked.
# ---------------------------------------------------------------------------


def _reobservation(repo: Path, **kwargs) -> dict:
    """The same register, re-observed: `next` is `current`, byte for byte."""
    manifest = _manifest(repo, **kwargs)
    manifest["kind"] = P.REOBSERVATION_KIND
    manifest["next"]["files"] = [dict(row) for row in manifest["current"]["files"]]
    return manifest


def test_a_reobservation_records_the_tree_and_authorises_nothing(tmp_path) -> None:
    repo, _base, _manifest_in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_reobservation(repo), 40)
    assert manifest["kind"] == P.REOBSERVATION_KIND
    assert P.moved_paths(manifest) == []

    live = [dict(row) for row in manifest["current"]["files"]]
    operation, base_id, candidate_id = P.classify_move(live, live, manifest)
    assert operation == "STEADY", operation
    assert base_id == candidate_id == manifest["next"]["id"]


def test_a_reobservation_that_hides_a_move_is_refused(tmp_path) -> None:
    """The NEW way to lie: declare no move and carry one anyway."""
    repo, _base, _manifest_in_tree = _repo(tmp_path)
    manifest = _reobservation(repo)
    victim = sorted(P.RUNTIME_PATHS)[0]
    manifest["next"]["files"] = [
        _record(repo, row["path"], b"smuggled:" + row["path"].encode())
        if row["path"] == victim else row
        for row in manifest["next"]["files"]]
    with pytest.raises(P.Refusal) as caught:
        P.parse_manifest(manifest, 40)
    assert "re-observation records no move" in str(caught.value)
    assert victim in str(caught.value)


def test_a_transition_that_moves_nothing_is_still_refused(tmp_path) -> None:
    """THE OLD REFUSAL, ON THE OLD SENTENCE. The re-observation kind is the
    ONLY thing that makes an empty move legal; a register that still calls
    itself a transition is the malformation `1f1749d2d`, `b161ec6e5` and
    `eda53573f` shipped, and it is refused exactly as before."""
    repo, _base, _manifest_in_tree = _repo(tmp_path)
    manifest = _reobservation(repo)
    manifest["kind"] = P.MANIFEST_KIND                # the ONLY difference
    with pytest.raises(P.Refusal) as caught:
        P.parse_manifest(manifest, 40)
    assert "manifest next tuple does not differ from current" in str(caught.value)


def test_under_a_reobservation_every_protected_move_is_undeclared(tmp_path) -> None:
    """STRICTER, NOT LOOSER. With nothing authorised, every protected path a
    candidate touches is undeclared, and the refusal still names it."""
    repo, _base, _manifest_in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_reobservation(repo), 40)
    live = [dict(row) for row in manifest["current"]["files"]]

    for victim in (sorted(P.RUNTIME_PATHS)[0],
                   sorted(P.REQUIRED_AUTHORITY_PATHS)[0]):
        candidate = [
            _record(repo, row["path"], b"undeclared:" + row["path"].encode())
            if row["path"] == victim else row
            for row in live]
        with pytest.raises(P.Refusal) as caught:
            P.classify_move(live, candidate, manifest)
        assert "authorises no move" in str(caught.value), str(caught.value)[:400]
        assert victim in str(caught.value), str(caught.value)[:400]


def test_an_unknown_register_kind_is_refused(tmp_path) -> None:
    repo, _base, _manifest_in_tree = _repo(tmp_path)
    manifest = _manifest(repo)
    manifest["kind"] = "vibeic.protected-landing-whatever"
    with pytest.raises(P.Refusal) as caught:
        P.parse_manifest(manifest, 40)
    assert "not a protected-landing register kind" in str(caught.value)


# ---------------------------------------------------------------------------
# `describes_tree` — THE QUESTION, WITHOUT THE VERDICT.
#
# `_match_state` was deleted at `3c9d6a2563` (v1.13.36) because it ANSWERED A
# LANDING: any unauthorised move of any protected path falsified both recorded
# tuples and refused every landing after it, for drift nobody could repair.
# `classify_move` replaced it and observes the base instead. What went with the
# refusal was the ability to ASK, and a commit that CARRIES a manifest is making
# a claim -- that the manifest was rendered against the tree it travels with --
# that nothing could check any more. MEASURED 2026-08-31 on `36139c9546`
# (v1.14.24): a manifest rendered by `protected_landing_manifest_author.py`
# against that exact tree was indistinguishable from one rendered two mains
# earlier.
#
# These four cases are the bidirectional control. Both recorded tuples are
# RECOGNISED and by the right id; drift of a single byte in a single path is
# None; and the predicate raises NOTHING, so restoring the question cannot
# restore the refusal that was retired with it.
# ---------------------------------------------------------------------------


def test_describes_tree_names_the_state_a_tuple_actually_is(tmp_path) -> None:
    repo, _base, _in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_manifest(repo), 40)
    current = [dict(row) for row in manifest["current"]["files"]]
    nxt = [dict(row) for row in manifest["next"]["files"]]
    assert current != nxt, "the fixture must record an actual move"

    assert P.describes_tree(current, manifest) == manifest["current"]["id"]
    assert P.describes_tree(nxt, manifest) == manifest["next"]["id"]


def test_describes_tree_is_none_when_one_path_drifted(tmp_path) -> None:
    """THE DIRECTION THAT MATTERS. A manifest rendered against another tree is
    exactly this: every path matches but the ones some landing moved."""
    repo, _base, _in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_manifest(repo), 40)
    victim = sorted(P.RUNTIME_PATHS)[0]
    for label in ("current", "next"):
        drifted = [
            _record(repo, row["path"], b"drifted:" + row["path"].encode())
            if row["path"] == victim else dict(row)
            for row in manifest[label]["files"]]
        assert P.describes_tree(drifted, manifest) is None, label


def test_describes_tree_answers_and_never_refuses(tmp_path) -> None:
    """It is a REPORTING predicate. If it could raise `Refusal` a caller could
    put it back in a landing path by accident, which is the shape v1.13.36
    removed. The drifted input above is the one that used to raise."""
    repo, _base, _in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_manifest(repo), 40)
    drifted = [_record(repo, row["path"], b"drifted:" + row["path"].encode())
               for row in manifest["current"]["files"]]
    assert P.describes_tree(drifted, manifest) is None
    assert P.describes_tree([], manifest) is None


def test_a_drifted_base_still_lands_with_the_predicate_restored(tmp_path) -> None:
    """THE RETIRED REFUSAL STAYS RETIRED. `classify_move` decides landings and
    does not consult `describes_tree`: a base whose tuple matches neither
    recorded state still classifies a candidate that moves nothing as STEADY."""
    repo, _base, _in_tree = _repo(tmp_path)
    manifest = P.parse_manifest(_manifest(repo), 40)
    victim = sorted(P.RUNTIME_PATHS)[0]
    drifted = [
        _record(repo, row["path"], b"unauthorised:" + row["path"].encode())
        if row["path"] == victim else dict(row)
        for row in manifest["current"]["files"]]

    assert P.describes_tree(drifted, manifest) is None
    operation, _base_id, _cand_id = P.classify_move(drifted, drifted, manifest)
    assert operation == "STEADY", operation


# ---------------------------------------------------------------------------
# IMAGE_RE, pinned on its own.
#
# MEASURED: loosening IMAGE_RE so the `@sha256:<64hex>` tail became optional left
# this whole file green. `test_runner_requires_digest_and_exact_hermetic_profile`
# feeds a tag, and that tag is refused twice over -- by the shape check and,
# independently and more strongly, by `image != RUNNER_IMAGE`. So nothing pinned
# the shape check's own behaviour and it could have been weakened silently.
#
# It still has work to do: `parse_manifest` is not the only caller, and "this is
# an immutable reference" is a claim worth being able to make about a string
# before knowing which string is expected. So it gets its own table.
# ---------------------------------------------------------------------------

_DIGEST_64 = "sha256:" + "a" * 64

IMAGE_RE_ACCEPTS = (
    f"ghcr.io/vibeic/vibeic-eda@{_DIGEST_64}",       # the published repository
    f"192.0.2.10:5000/vibeic-eda@{_DIGEST_64}",      # a registry on a port
    f"registry.example.invalid/ns/name@{_DIGEST_64}",
    f"vibeic-eda@{_DIGEST_64}",                      # no registry host at all
)

IMAGE_RE_REFUSES = (
    "ghcr.io/vibeic/vibeic-eda:latest",              # a TAG is not a reference
    "ghcr.io/vibeic/vibeic-eda",                     # nor is a bare name
    "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 63,  # 63 hex
    "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 65,  # 65 hex
    "ghcr.io/vibeic/vibeic-eda@sha256:" + "g" * 64,  # not hex
    "ghcr.io/vibeic/vibeic-eda@md5:" + "a" * 32,     # not sha256
    f"GHCR.io/vibeic/vibeic-eda@{_DIGEST_64}",       # uppercase host
    f"ghcr.io/vibeic/vibeic-eda@{_DIGEST_64} ",      # trailing space
    f"ghcr.io/vibeic/vibeic-eda@{_DIGEST_64}\n",     # trailing newline
    f"@{_DIGEST_64}",                                # no repository at all
    "",
)


@pytest.mark.parametrize("reference", IMAGE_RE_ACCEPTS)
def test_image_re_accepts_an_immutable_reference(reference: str) -> None:
    assert P.IMAGE_RE.fullmatch(reference) is not None, reference


@pytest.mark.parametrize("reference", IMAGE_RE_REFUSES)
def test_image_re_refuses_anything_that_is_not_one(reference: str) -> None:
    assert P.IMAGE_RE.fullmatch(reference) is None, reference


def test_image_re_requires_the_digest_and_not_merely_a_plausible_name() -> None:
    """The single property that must never be relaxed: no digest, no reference."""
    for accepted in IMAGE_RE_ACCEPTS:
        assert "@sha256:" in accepted
    assert P.IMAGE_RE.fullmatch("ghcr.io/vibeic/vibeic-eda") is None
