"""Synthetic controls for the private host NDA boundary; no real detector data."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import trusted_nda_host as nda  # noqa: E402
import landing_completion_record as completion  # noqa: E402
import landing_push_preflight as preflight  # noqa: E402
import hermetic_git_subject as git_subject  # noqa: E402
import hermetic_candidate_runner as candidate_runner  # noqa: E402

PROGRAMS = ROOT / "vibe-ic-marketplace/plugins/vibe-ic/programs"
sys.path.insert(0, str(PROGRAMS / "tests"))
from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS as SYNTHETIC  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, text=True)
    return p.stdout.strip()


@pytest.fixture
def subject(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG", raising=False)
    monkeypatch.delenv("VIBEIC_NDA_TOKENS", raising=False)
    repo = tmp_path / "subject"
    repo.mkdir()
    target = repo / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    target.mkdir(parents=True)
    for source in nda.SOURCE:
        (target / source).write_bytes((PROGRAMS / source).read_bytes())
    (repo / "design.txt").write_text("ordinary example\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@localhost")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "design.txt").write_text("ordinary updated example\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "update example")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _completion(path: Path, arm: str, base: str, head: str, tree: str) -> None:
    gates = [{"index": i, "label": label,
              "output_sha256": "a" * 64, "returncode": 0,
              "state": "SKIP" if arm == "A2" and label in {
                  "cheap:nda-messages", "cheap:nda-content"} else "PASS"}
             for i, label in enumerate(completion.LANDING_PROGRESS_UNITS)]
    digest = {"sha256": "b" * 64, "size": 1}
    payload = {"arm": arm, "base": base, "head": head, "tree": tree,
               "benchmark_data_sha": "c" * 40, "failed": 0, "gates": gates,
               "hygiene": digest, "progress_nonce": "d" * 64,
               "progress_plan": digest, "selection": digest, "returncode": 0}
    record = {"schema": completion.SCHEMA, "kind": completion.KIND,
              "complete": True, "payload": payload,
              "payload_sha256": hashlib.sha256(
                  completion.strict.canonical_bytes(payload)).hexdigest()}
    completion.parse_record(record)
    path.write_bytes(completion.strict.canonical_bytes(record))


def test_host_guards_and_completion_binding(subject, tmp_path, monkeypatch):
    repo, base, head = subject
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", "{bad-json")
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(
        {"sku_full": SYNTHETIC["sku_full"]}))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    malformed_file = tmp_path / "bad-private-config.json"
    malformed_file.write_text('{"nda_tokens": []}\n')
    monkeypatch.setenv("VIBEIC_PRIVATE_CONFIG", str(malformed_file))
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG")
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    clean = nda.run(repo, base, head)
    assert [g["rc"] for g in clean["payload"]["guards"]] == [0, 0]
    raw = nda._canonical(clean)
    assert SYNTHETIC["sku_full"].encode() not in raw
    record = tmp_path / "host.json"
    record.write_bytes(raw)
    base_tree = _git(repo, "rev-parse", f"{base}^{{tree}}")
    tree = _git(repo, "rev-parse", f"{head}^{{tree}}")
    a2, b2 = tmp_path / "a2.json", tmp_path / "b2.json"
    _completion(a2, "A2", base, base, base_tree)
    _completion(b2, "B2", base, head, tree)
    nda.verify(record, repo, base, head, tree, a2, b2)
    with pytest.raises(nda.Refusal):
        nda.verify(record, repo, base, head, base_tree, a2, b2)

    # Reverse mutation: the same synthetic detector now finds the forbidden
    # subject. Neither the returned receipt nor captured CLI output contains it.
    (repo / "design.txt").write_text(SYNTHETIC["sku_full"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "update fictional fixture")
    forbidden = nda.run(repo, base, _git(repo, "rev-parse", "HEAD"))
    assert any(g["rc"] == 1 for g in forbidden["payload"]["guards"])
    assert SYNTHETIC["sku_full"].encode() not in nda._canonical(forbidden)


def test_child_cannot_replace_host_proof(subject, tmp_path, monkeypatch):
    repo, base, head = subject
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    record = tmp_path / "host.json"
    record.write_bytes(nda._canonical(nda.run(repo, base, head)))
    base_tree = _git(repo, "rev-parse", f"{base}^{{tree}}")
    tree = _git(repo, "rev-parse", f"{head}^{{tree}}")
    a2, b2 = tmp_path / "a2.json", tmp_path / "b2.json"
    _completion(a2, "A2", base, base, base_tree)
    _completion(b2, "B2", base, head, tree)
    altered = json.loads(b2.read_text())
    altered["payload"]["gates"][0]["state"] = "SKIP"
    altered["payload_sha256"] = hashlib.sha256(
        completion.strict.canonical_bytes(altered["payload"])).hexdigest()
    b2.write_bytes(completion.strict.canonical_bytes(altered))
    with pytest.raises(nda.Refusal):
        nda.verify(record, repo, base, head, tree, a2, b2)


def test_cli_refusals_are_fixed_and_do_not_echo_detector(subject, tmp_path):
    repo, base, head = subject
    command = [sys.executable, "-B", str(HERE / "trusted_nda_host.py"),
               "run", "--repo", str(repo), "--base", base, "--head", head]
    env = {"PATH": os.defpath, "HOME": str(tmp_path / "empty-home")}
    missing = subprocess.run(command + ["--record", str(tmp_path / "missing.json")],
                             env=env, capture_output=True)
    assert missing.returncode == 2
    assert missing.stderr == b"[NORECORD] trusted host NDA boundary refused\n"
    malformed = subprocess.run(command + ["--record", str(tmp_path / "malformed.json")],
                               env={**env, "VIBEIC_NDA_TOKENS": "{bad-json"},
                               capture_output=True)
    assert malformed.returncode == 2
    assert malformed.stderr == missing.stderr
    (repo / "design.txt").write_text(SYNTHETIC["sku_full"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional forbidden text")
    planted = _git(repo, "rev-parse", "HEAD")
    forbidden = subprocess.run(
        command[:-1] + [planted, "--record", str(tmp_path / "forbidden.json")],
        env={**env, "VIBEIC_NDA_TOKENS": json.dumps(SYNTHETIC)},
        capture_output=True)
    assert forbidden.returncode == 1
    assert forbidden.stderr == b"[REFUSE] trusted host NDA guard found forbidden content\n"
    assert SYNTHETIC["sku_full"].encode() not in (
        forbidden.stdout + forbidden.stderr
        + (tmp_path / "forbidden.json").read_bytes())


def test_partial_default_config_cannot_certify_other_roles(subject, tmp_path,
                                                           monkeypatch):
    repo, base, head = subject
    home = tmp_path / "private-home"
    config = home / ".config/vibeic/commercial_pdk.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"nda_tokens": {
        "sku_full": SYNTHETIC["sku_full"]}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VIBEIC_NDA_TOKENS", raising=False)
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG", raising=False)
    (repo / "design.txt").write_text(SYNTHETIC["ip_part"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional role counterexample")
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, _git(repo, "rev-parse", "HEAD"))


def test_duplicate_values_cannot_certify_all_roles(subject, monkeypatch):
    repo, base, head = subject
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps({
        role: SYNTHETIC["sku_full"] for role in nda.ROLES}))
    (repo / "design.txt").write_text(SYNTHETIC["ip_part"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional role counterexample")
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, _git(repo, "rev-parse", "HEAD"))


def test_default_config_precedence_and_symlink_are_exact(subject, tmp_path,
                                                         monkeypatch):
    repo, base, head = subject
    home = tmp_path / "private-home"
    default = home / ".config/vibeic/commercial_pdk.json"
    default.parent.mkdir(parents=True)
    default.write_text(json.dumps({"nda_tokens": SYNTHETIC}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VIBEIC_NDA_TOKENS", raising=False)
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG", raising=False)
    assert [g["rc"] for g in nda.run(repo, base, head)["payload"]["guards"]] == [0, 0]
    explicit = tmp_path / "empty-config.json"
    explicit.write_text("{}\n")
    monkeypatch.setenv("VIBEIC_PRIVATE_CONFIG", str(explicit))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG")
    default.unlink()
    default.symlink_to(explicit)
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)


def test_regex_equivalent_role_values_cannot_certify(subject, monkeypatch):
    repo, base, head = subject
    aliases = dict(SYNTHETIC)
    aliases["ip_part"] = aliases["sku_full"].swapcase()
    assert aliases["ip_part"] != aliases["sku_full"]
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(aliases))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)
    aliases = dict(SYNTHETIC)
    aliases["ip_part"] = aliases["foundry_brand2"].replace(" ", "_")
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(aliases))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)


def test_one_way_separator_alias_with_distinct_roles_is_valid(subject, monkeypatch):
    repo, base, head = subject
    aliases = dict(SYNTHETIC)
    aliases["foundry_brand1"] = aliases["foundry_brand2"].replace(" ", "")
    assert len(set(aliases.values())) == len(aliases)
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(aliases))
    clean = nda.run(repo, base, head)
    assert [row["rc"] for row in clean["payload"]["guards"]] == [0, 0]
    assert all(value.encode() not in nda._canonical(clean)
               for value in aliases.values())


@pytest.mark.parametrize("case", ["benign", "forbidden", "malformed", "source_binding"])
def test_normal_host_boundary_on_materialized_shallow_subject(subject, tmp_path, monkeypatch, case):
    repo, _, base = subject
    (repo / "design.txt").write_text(
        SYNTHETIC["sku_full"] + "\n" if case == "forbidden" else "ordinary third version\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "candidate update")
    head = _git(repo, "rev-parse", "HEAD")
    shallow = tmp_path / "shallow-source"
    subprocess.run(["git", "clone", "-q", "--no-local", "--depth", "2", repo.as_uri(), str(shallow)],
                   check=True, capture_output=True)
    materialized = tmp_path / "materialized"
    git_subject.materialize(shallow, head, materialized)
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", "{bad-json" if case == "malformed" else json.dumps(SYNTHETIC))
    reviewed = {"GATEKEEPER_VERIFY_ARM": "B2", "GATEKEEPER_BASE": base}
    command = ["/subject/tools/gatekeeper-land.sh"]
    if case == "forbidden":
        with pytest.raises(candidate_runner.NDARejection):
            candidate_runner._prepare_host_nda(materialized, reviewed, command)
    elif case == "malformed":
        with pytest.raises(candidate_runner.Refusal):
            candidate_runner._prepare_host_nda(materialized, reviewed, command)
    else:
        result = candidate_runner._prepare_host_nda(materialized, reviewed, command)
        assert [g["rc"] for g in result["payload"]["guards"]] == [0, 0]
        raw = nda._canonical(result).decode().strip()
        nda.verify_unit(raw, materialized, base, nda.GUARDS[0])
        if case == "source_binding":
            result["payload"]["source_sha256"][nda.SOURCE[0]] = "0" * 64
            with pytest.raises(nda.Refusal):
                nda.verify_unit(nda._canonical(result).decode().strip(), materialized, base, nda.GUARDS[0])


def test_config_rotation_before_guard_spawn_cannot_change_detector(
        subject, tmp_path, monkeypatch):
    repo, base, head = subject
    home = tmp_path / "private-home"
    config = home / ".config/vibeic/commercial_pdk.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"nda_tokens": SYNTHETIC}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VIBEIC_NDA_TOKENS", raising=False)
    monkeypatch.delenv("VIBEIC_PRIVATE_CONFIG", raising=False)
    (repo / "design.txt").write_text(SYNTHETIC["ip_part"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional role counterexample")
    planted = _git(repo, "rev-parse", "HEAD")
    real_run = subprocess.run
    rotated = False
    snapshots = []

    def rotate_before_first_guard(argv, *args, **kwargs):
        nonlocal rotated
        if (isinstance(argv, list) and len(argv) > 2
                and argv[0] == sys.executable and argv[1] == "-B"
                and str(argv[2]).endswith(nda.GUARDS)):
            snapshots.append(kwargs["env"]["VIBEIC_NDA_TOKENS"])
            assert kwargs["env"]["VIBEIC_PRIVATE_CONFIG"] != str(config)
            if not rotated:
                config.write_text(json.dumps({"nda_tokens": {
                    "sku_full": SYNTHETIC["sku_full"]}}))
                rotated = True
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(nda.subprocess, "run", rotate_before_first_guard)
    result = nda.run(repo, base, planted)
    assert rotated
    assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
    assert any(row["rc"] == 1 for row in result["payload"]["guards"])


def test_existing_push_preflight_receipt_redacts_nda_streams():
    token = SYNTHETIC["sku_full"].encode()
    proc = subprocess.CompletedProcess([], 1, token, token)
    row = preflight._gate_record("nda_diff_scan_check.py", proc)
    assert row["summary"] == "NDA guard REFUSE"
    assert token not in json.dumps(row).encode()
    assert row["stdout_sha256"] == row["stderr_sha256"] == "0" * 64


def _runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_nda_test_runner", HERE / "hermetic_candidate_runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_measures_host_before_candidate_and_rejects_forbidden_range(
        subject, monkeypatch):
    repo, base, head = subject
    runner = _runner()
    reviewed = {"GATEKEEPER_VERIFY_ARM": "B2", "GATEKEEPER_BASE": base}
    command = ["/subject/tools/gatekeeper-land.sh"]
    with pytest.raises(runner.Refusal, match="unavailable or invalid"):
        runner._prepare_host_nda(repo, reviewed, command)
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    result = runner._prepare_host_nda(repo, reviewed, command)
    assert [g["rc"] for g in result["payload"]["guards"]] == [0, 0]
    assert result["payload"]["head"] == head
    assert all(token.encode() not in nda._canonical(result) for token in SYNTHETIC.values())
    nda.verify_unit(nda._canonical(result).decode().strip(), repo, base, nda.GUARDS[0])
    (repo / "design.txt").write_text(SYNTHETIC["ip_part"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional forbidden fixture")
    with pytest.raises(nda.Refusal):
        nda.verify_unit(nda._canonical(result).decode().strip(), repo, base, nda.GUARDS[0])
    with pytest.raises(runner.NDARejection):
        runner._prepare_host_nda(repo, reviewed, command)


def test_runner_requires_measured_b2_pass_in_exact_completion(subject, tmp_path, monkeypatch):
    repo, base, head = subject
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    result = nda.run(repo, base, head)
    completion_path = tmp_path / "completion.json"
    _completion(completion_path, "B2", base, head, _git(repo, "rev-parse", "HEAD^{tree}"))
    nda.verify_completion(result["payload"], repo, completion_path, "B2")
    altered = json.loads(completion_path.read_text())
    altered["payload"]["gates"][0]["state"] = "SKIP"
    altered["payload_sha256"] = hashlib.sha256(
        completion.strict.canonical_bytes(altered["payload"])).hexdigest()
    completion_path.write_bytes(completion.strict.canonical_bytes(altered))
    with pytest.raises(nda.Refusal):
        nda.verify_completion(result["payload"], repo, completion_path, "B2")


def test_unstamped_hermetic_context_required_for_public_result(subject, monkeypatch):
    repo, base, head = subject
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    record = nda._canonical(nda.run(repo, base, head)).decode().strip()
    command = [sys.executable, str(HERE / "trusted_nda_host.py"), "check-unit",
               "--repo", str(repo), "--base", base, "--guard", nda.GUARDS[0]]
    env = {"PATH": os.defpath, "HOME": str(repo.parent / "empty-home"),
           "VIBEIC_NDA_HOST_RESULT": record}
    refused = subprocess.run(command, env=env, capture_output=True, text=True)
    assert refused.returncode == 2
    env.update(VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY="1", GATEKEEPER_NO_STAMP="1",
               GATEKEEPER_RUNTIME_ROOT="/runtime")
    passed = subprocess.run(command, env=env, capture_output=True, text=True)
    assert passed.returncode == 0
    altered = json.loads(record)
    altered["payload"]["source_sha256"]["_commercial_pdk.py"] = "0" * 64
    env["VIBEIC_NDA_HOST_RESULT"] = nda._canonical(altered).decode().strip()
    refused = subprocess.run(command, env=env, capture_output=True, text=True)
    assert refused.returncode == 2


def test_candidate_cannot_supply_the_detector_configuration(subject, monkeypatch):
    repo, base, head = subject
    config = repo / "detector.json"
    config.write_text(json.dumps({"nda_tokens": SYNTHETIC}))
    monkeypatch.setenv("VIBEIC_PRIVATE_CONFIG", str(config))
    with pytest.raises(nda.Refusal):
        nda.run(repo, base, head)


def test_detector_configuration_cannot_be_mounted_in_runtime(subject, tmp_path, monkeypatch):
    repo, base, head = subject
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = runtime / "detector.json"
    config.write_text(json.dumps({"nda_tokens": SYNTHETIC}))
    monkeypatch.setenv("VIBEIC_PRIVATE_CONFIG", str(config))
    runner = _runner()
    with pytest.raises(runner.Refusal):
        runner._prepare_host_nda(repo, {"GATEKEEPER_BASE": base,
            "GATEKEEPER_VERIFY_ARM": "B2"}, ["/subject/tools/gatekeeper-land.sh"], runtime)


def test_boolean_return_code_cannot_become_host_measurement(subject, monkeypatch):
    repo, base, head = subject
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(SYNTHETIC))
    record = nda.run(repo, base, head)
    record["payload"]["guards"][0]["rc"] = False
    with pytest.raises(nda.Refusal):
        nda.public_result(nda._canonical(record).decode().strip())


def test_cli_keeps_benign_and_forbidden_return_codes_distinct(subject, tmp_path):
    repo, base, head = subject
    env = {"PATH": os.defpath, "HOME": str(tmp_path / "empty-home"),
           "VIBEIC_NDA_TOKENS": json.dumps(SYNTHETIC)}
    def check(revision, name):
        command = [sys.executable, str(HERE / "trusted_nda_host.py"), "run",
                   "--repo", str(repo), "--base", base, "--head", revision,
                   "--record", str(tmp_path / name)]
        return subprocess.run(command, env=env, capture_output=True, text=True)
    benign = check(head, "benign.json")
    assert benign.returncode == 0
    (repo / "design.txt").write_text(SYNTHETIC["ip_part"] + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fictional counterexample")
    forbidden = check(_git(repo, "rev-parse", "HEAD"), "forbidden.json")
    assert forbidden.returncode == 1
    assert all(token not in forbidden.stdout + forbidden.stderr
               for token in SYNTHETIC.values())


def test_host_reader_loads_from_an_isolated_verifier_process(tmp_path):
    """The final receipt reader loads by file path, without tools/ci on sys.path."""
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('verifier', {str(HERE / 'hermetic_candidate_runner.py')!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(module._nda_host().KIND)\n"
    )
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "vibeic.trusted-host-nda/v1"
