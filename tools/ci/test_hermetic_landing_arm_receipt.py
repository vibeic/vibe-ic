from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


V = _load(
    "hermetic_landing_arm_receipt", HERE / "hermetic_landing_arm_receipt.py")
SUPPORT = _load(
    "_hermetic_candidate_runner_test_support",
    HERE / "test_hermetic_candidate_runner.py")
R = SUPPORT.runner
C = _load("_landing_completion_record_test_support",
          HERE / "landing_completion_record.py")

BENCHMARK = "b" * 40
BASE = "a" * 40
HEAD = "d" * 40
TREE = "e" * 40
LANDING_NONCE = "c" * 64
TEST_ENTRY = "tools/ci/hermetic_test_arm_entry.sh"
MATRIX_LEDGER = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/"
    "matrix_mutation_ledger.py"
)
MATRIX_CENSUS_TEST = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_flow_matrix_census_freshness.py"
)
MATRIX_TEST = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_flow_matrix_coverage.py"
)
MATRIX_ARTEFACT_TEST = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_matrix_artefact_mutation_channel.py"
)
MATRIX_MUTATION_TEST = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_matrix_mutation_ledger.py"
)
TEST_OVERLAYS = (
    TEST_ENTRY, MATRIX_LEDGER, MATRIX_CENSUS_TEST, MATRIX_TEST,
    MATRIX_ARTEFACT_TEST, MATRIX_MUTATION_TEST,
)
LAND_ENTRY = "tools/gatekeeper-land.sh"


def _command(arm: str) -> str:
    return "/subject/" + (TEST_ENTRY if arm in {"A1", "B1"} else LAND_ENTRY)


def _case(tmp_path: Path) -> dict[str, Path]:
    case = SUPPORT.case.__wrapped__(tmp_path)
    source = (case["runtime"] / "candidate.py").read_bytes()
    for root in (case["subject"], case["runtime"]):
        for rel, mode in (
                *((rel, 0o755 if rel == TEST_ENTRY else 0o644)
                  for rel in TEST_OVERLAYS),
                (LAND_ENTRY, 0o755)):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
            target.chmod(mode)
    return case


def _invoke(case: dict[str, Path], arm: str, *, behavior: str = "good"):
    env = dict(os.environ)
    env["FAKE_DOCKER_STATE"] = str(case["state"])
    env["FAKE_DOCKER_BEHAVIOR"] = behavior
    if arm in {"A1", "B1"}:
        reviewed = {
            "GATEKEEPER_BENCHMARK_DATA_SHA": BENCHMARK,
            "GATEKEEPER_VERIFY_ARM": arm,
            "VIBEIC_PYTEST_PROGRESS_FILE": "/evidence/pytest-progress.jsonl",
            "VIBEIC_PYTEST_PROGRESS_NONCE": "f" * 64,
        }
    else:
        reviewed = {
            "GATEKEEPER_BASE": BASE,
            "GATEKEEPER_BENCHMARK_DATA_SHA": BENCHMARK,
            "GATEKEEPER_HYGIENE_PROGRESS": "/evidence/hygiene-progress.jsonl",
            "GATEKEEPER_HYGIENE_REPORT": "/evidence/hygiene.json",
            "GATEKEEPER_VERIFY_ARM": arm,
            "GATEKEEPER_VERSION_BY_GATEKEEPER": "1",
            "VIBEIC_LANDING_PROGRESS_NONCE": LANDING_NONCE,
        }
    overlays = (list(TEST_OVERLAYS)
                if arm in {"A1", "B1"} else [LAND_ENTRY])
    command = [
        sys.executable, str(SUPPORT.RUNNER_PATH), "run",
        "--docker-bin", str(case["docker"]),
        "--subject", str(case["subject"]),
        "--runtime", str(case["runtime"]),
    ]
    for overlay in overlays:
        command.extend(("--overlay", overlay))
    for name in sorted(reviewed):
        command.extend(("--env", f"{name}={reviewed[name]}"))
    command.extend((
        "--corpus", str(case["corpus"]),
        "--selection", str(case["selection"]),
        "--progress-plan", str(case["plan"]),
        "--output-dir", str(case["output"]),
        "--receipt", str(case["receipt"]),
        "--", _command(arm),
    ))
    return subprocess.run(
        command, env=env, text=True, capture_output=True, check=False)


def _pytest_case(tmp_path: Path, arm: str = "A1") -> dict[str, Path]:
    case = _case(tmp_path)
    proc = _invoke(case, arm)
    assert proc.returncode == 0, proc.stderr
    return case


def _receipt(case: dict[str, Path]) -> dict:
    return R.strict_load_receipt(case["receipt"])


def _write_receipt(case: dict[str, Path], receipt: dict) -> None:
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = R._sha256(R._canonical(body))
    case["receipt"].write_bytes(R._canonical(receipt) + b"\n")
    R.strict_load_receipt(case["receipt"])


def _refresh_artifacts(case: dict[str, Path]) -> None:
    receipt = _receipt(case)
    receipt["artifacts"] = R._artefact_manifest(case["output"])
    _write_receipt(case, receipt)


def _completion_payload(receipt: dict, arm: str, hygiene: Path) -> dict:
    hygiene_raw = hygiene.read_bytes()
    gates = [{
        "index": index,
        "label": label,
        "output_sha256": f"{index % 16:x}" * 64,
        "returncode": 0,
        "state": "PASS",
    } for index, label in enumerate(C.LANDING_PROGRESS_UNITS)]
    return {
        "arm": arm,
        "base": BASE,
        "benchmark_data_sha": BENCHMARK,
        "failed": 0,
        "gates": gates,
        "head": HEAD,
        "hygiene": {
            "sha256": hashlib.sha256(hygiene_raw).hexdigest(),
            "size": len(hygiene_raw),
        },
        "progress_nonce": LANDING_NONCE,
        "progress_plan": receipt["inputs"]["runtime_progress_plan"],
        "returncode": 0,
        "selection": {
            key: receipt["inputs"]["selection"][key]
            for key in ("sha256", "size")
        },
        "tree": TREE,
    }


def _write_completion(case: dict[str, Path], payload: dict) -> None:
    record = {
        "schema": C.SCHEMA,
        "kind": C.KIND,
        "complete": True,
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            C.strict.canonical_bytes(payload)).hexdigest(),
    }
    C.parse_record(record)
    (case["output"] / "landing-completion.json").write_bytes(
        C.strict.canonical_bytes(record))


def _landing_case(tmp_path: Path, arm: str = "A2") -> dict[str, Path]:
    case = _case(tmp_path)
    proc = _invoke(case, arm)
    assert proc.returncode == 0, proc.stderr
    hygiene = case["output"] / "hygiene.json"
    hygiene.write_text('{"complete":true,"schema":1}\n', encoding="utf-8")
    _write_completion(case, _completion_payload(_receipt(case), arm, hygiene))
    _refresh_artifacts(case)
    return case


def _validate_kwargs(case: dict[str, Path], arm: str = "A1") -> dict:
    values = {
        "runner_path": SUPPORT.RUNNER_PATH,
        "receipt_path": case["receipt"],
        "output_dir": case["output"],
        "arm": arm,
        "subject": case["subject"],
        "runtime": case["runtime"],
        "corpus": case["corpus"],
        "selection": case["selection"],
        "progress_plan": case["plan"],
        "benchmark_sha": BENCHMARK,
        "command": _command(arm),
    }
    if arm in {"A2", "B2"}:
        values.update({
            "completion": "landing-completion.json",
            "base": BASE,
            "head": HEAD,
            "hygiene": "hygiene.json",
        })
    return values


def _validate_argv(case: dict[str, Path], arm: str, record: Path) -> list[str]:
    args = [
        "validate",
        "--runner", str(SUPPORT.RUNNER_PATH),
        "--receipt", str(case["receipt"]),
        "--output-dir", str(case["output"]),
        "--arm", arm,
        "--subject", str(case["subject"]),
        "--runtime", str(case["runtime"]),
        "--corpus", str(case["corpus"]),
        "--selection", str(case["selection"]),
        "--progress-plan", str(case["plan"]),
        "--benchmark-sha", BENCHMARK,
        "--command", _command(arm),
    ]
    if arm in {"A2", "B2"}:
        args.extend((
            "--completion", "landing-completion.json",
            "--base", BASE,
            "--head", HEAD,
            "--hygiene", "hygiene.json",
        ))
    args.extend(("--record", str(record)))
    return args


@pytest.mark.parametrize("arm", ["A1", "B1"])
def test_valid_pytest_arm_cli_record_and_publish(tmp_path, arm):
    case = _pytest_case(tmp_path, arm)
    record_path = tmp_path / "validation.json"
    assert V.main(_validate_argv(case, arm, record_path)) == 0
    record = V.strict_load_record(record_path)
    assert record["payload"]["arm"] == arm
    assert record["payload"]["completion"] is None
    assert record["payload"]["result_exit_code"] == 0
    assert record["payload"]["receipt"]["receipt_sha256"] == (
        _receipt(case)["receipt_sha256"])
    destination = tmp_path / "published-result.txt"
    assert V.main([
        "publish", "--record", str(record_path),
        "--output-dir", str(case["output"]),
        "--artifact", "result.txt",
        "--destination", str(destination),
    ]) == 0
    assert destination.read_text(encoding="utf-8") == "candidate evidence\n"
    assert stat_mode(destination) == 0o600


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize(
    "target",
    ["subject", "runtime", "corpus", "selection", "plan"],
)
def test_mutated_input_is_refused(tmp_path, target):
    case = _pytest_case(tmp_path)
    if target == "subject":
        (case["subject"] / "candidate.py").write_text(
            "print('changed subject')\n", encoding="utf-8")
    elif target == "runtime":
        (case["runtime"] / "candidate.py").write_text(
            "#!/usr/bin/python3\n# changed runtime\n", encoding="utf-8")
    elif target == "corpus":
        (case["corpus"] / "one.def").write_text(
            "VERSION 5.9 ;\n", encoding="utf-8")
    elif target == "selection":
        case["selection"].write_text('{"schema":2}\n', encoding="utf-8")
    else:
        plan = json.loads(case["plan"].read_text(encoding="utf-8"))
        plan["stall_grace_seconds"] = 2
        case["plan"].write_text(
            SUPPORT.canonical(plan) + "\n", encoding="utf-8")
    with pytest.raises(V.Refusal):
        V.validate(**_validate_kwargs(case))


@pytest.mark.parametrize("target", ["selection", "plan", "receipt"])
def test_a_relinked_parent_owned_input_is_refused_with_identical_bytes(
        tmp_path, target):
    """A parent-owned input that was RELINKED, byte for byte, is still refused.

    The sibling above moves the BYTES, which every content digest in the chain
    sees. This moves only the inode and the file TYPE, and almost nothing sees
    that: `hermetic_candidate_runner._resolve_mount` calls
    `path.resolve(strict=True)` BEFORE it checks `S_ISREG`, so a symlinked
    input arrives as its resolved regular target and every later
    `_read_regular` is satisfied; the merge verifier's own `cmp` of the
    selection against the selection it regenerates compares content, which is
    identical by construction. `_resolved_file` is the one clause in the
    repository that lstats the SUPPLIED path, and until this test nothing
    drove it with a relinked arm input — the artifact and validation-record
    symlink guards below cover different paths and match on "single-link".

    MEASURED 2026-08-22 end to end, relinking the parent-owned selection while
    the candidate wave was in flight: with this clause disabled the run LANDS
    OK, and with it the run is rc 2 with no verdict document at all.
    """
    case = _pytest_case(tmp_path)
    # THE PAIRED CONTROL FIRST: this exact case validates before the relink, so
    # the refusal below is about the relink and not about the fixture.
    V.validate(**_validate_kwargs(case))

    path = case[target]
    copy = path.parent / f"{path.name}.identical-copy"
    copy.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy)
    assert path.read_bytes() == copy.read_bytes(), "the bytes must be identical"

    with pytest.raises(V.Refusal, match="direct regular file"):
        V.validate(**_validate_kwargs(case))


def test_mutated_artifact_is_refused_during_validation(tmp_path):
    case = _pytest_case(tmp_path)
    (case["output"] / "result.txt").write_text(
        "forged evidence\n", encoding="utf-8")
    with pytest.raises(V.Refusal, match="artifact manifest"):
        V.validate(**_validate_kwargs(case))


@pytest.mark.parametrize("missing", TEST_OVERLAYS[1:])
def test_pytest_arm_cannot_omit_a_parent_owned_progress_overlay(
        tmp_path, missing):
    case = _pytest_case(tmp_path)
    receipt = _receipt(case)
    receipt["inputs"]["overlays"] = [
        row for row in receipt["inputs"]["overlays"]
        if row["path"] != missing
    ]
    role = f"runtime_overlay:{missing}"
    receipt["container"]["mounts"] = [
        row for row in receipt["container"]["mounts"]
        if row["role"] != role
    ]
    _write_receipt(case, receipt)
    with pytest.raises(V.Refusal, match="exact arm runtime overlays"):
        V.validate(**_validate_kwargs(case))


@pytest.mark.parametrize(
    "tamper",
    ["environment", "vibe_path", "command", "mount"],
)
def test_receipt_environment_command_and_mount_are_exact(tmp_path, tamper):
    case = _pytest_case(tmp_path)
    receipt = _receipt(case)
    if tamper in {"environment", "vibe_path"}:
        old_prefix = (
            "GATEKEEPER_BENCHMARK_DATA_SHA=" if tamper == "environment"
            else "VIBE_IC_BENCHMARK_DATA=")
        replacement = (
            old_prefix + "9" * 40 if tamper == "environment"
            else old_prefix + "/not-corpus")
        receipt["container"]["process_environment"] = sorted(
            replacement if item.startswith(old_prefix) else item
            for item in receipt["container"]["process_environment"])
    elif tamper == "command":
        receipt["container"]["command"] = [
            _command("A1"), "--forged-argument"]
    else:
        mount = next(
            row for row in receipt["container"]["mounts"]
            if row["role"] == "subject")
        mount["source"] = str(case["corpus"].resolve())
    body = dict(receipt)
    body.pop("receipt_sha256")
    receipt["receipt_sha256"] = R._sha256(R._canonical(body))
    case["receipt"].write_bytes(R._canonical(receipt) + b"\n")
    with pytest.raises(V.Refusal):
        V.validate(**_validate_kwargs(case))


def test_natural_exit_one_is_a_valid_pytest_result(tmp_path):
    case = _pytest_case(tmp_path)
    receipt = _receipt(case)
    receipt["result"]["attach_exit_code"] = 1
    receipt["result"]["exit_code"] = 1
    _write_receipt(case, receipt)
    record = V.validate(**_validate_kwargs(case))
    assert record["payload"]["result_exit_code"] == 1


def test_exit_outside_zero_one_is_norecord(tmp_path):
    case = _case(tmp_path)
    proc = _invoke(case, "A1", behavior="exit7")
    assert proc.returncode == 1
    assert _receipt(case)["result"]["exit_code"] == 7
    with pytest.raises(V.Refusal, match="0 or 1"):
        V.validate(**_validate_kwargs(case))


@pytest.mark.parametrize("arm", ["A2", "B2"])
def test_valid_landing_arm_strict_completion_path(tmp_path, arm):
    case = _landing_case(tmp_path, arm)
    record_path = tmp_path / "landing-validation.json"
    assert V.main(_validate_argv(case, arm, record_path)) == 0
    record = V.strict_load_record(record_path)
    binding = record["payload"]["completion"]
    assert binding["base"] == BASE
    assert binding["head"] == HEAD
    assert binding["path"] == "landing-completion.json"
    assert binding["hygiene"]["path"] == "hygiene.json"
    assert record["payload"]["inputs"]["runtime_progress_plan"] == (
        _receipt(case)["inputs"]["runtime_progress_plan"])


@pytest.mark.parametrize(
    "field",
    ["arm", "base", "benchmark", "head", "result", "selection",
     "runtime_plan", "hygiene", "nonce"],
)
def test_landing_completion_mismatch_is_refused(tmp_path, field):
    case = _landing_case(tmp_path)
    completion_path = case["output"] / "landing-completion.json"
    record = C.strict_load_record(completion_path)
    payload = copy.deepcopy(record["payload"])
    if field == "arm":
        payload["arm"] = "B2"
    elif field == "base":
        payload["base"] = "8" * 40
    elif field == "benchmark":
        payload["benchmark_data_sha"] = "8" * 40
    elif field == "head":
        payload["head"] = "8" * 40
    elif field == "result":
        payload["failed"] = 1
        payload["returncode"] = 1
        payload["gates"][0]["state"] = "FAIL"
        payload["gates"][0]["returncode"] = 1
    elif field == "selection":
        payload["selection"] = {"sha256": "8" * 64, "size": 17}
    elif field == "runtime_plan":
        payload["progress_plan"] = {"sha256": "8" * 64, "size": 19}
    elif field == "hygiene":
        payload["hygiene"] = {"sha256": "8" * 64, "size": 23}
    else:
        payload["progress_nonce"] = "8" * 64
    _write_completion(case, payload)
    _refresh_artifacts(case)
    with pytest.raises(V.Refusal, match="completion binding"):
        V.validate(**_validate_kwargs(case, "A2"))


def test_publish_rechecks_mutation_and_accepts_exact_restore_before_seal(
        tmp_path):
    case = _pytest_case(tmp_path)
    record_path = tmp_path / "validation.json"
    V.write_record(record_path, V.validate(**_validate_kwargs(case)))
    source = case["output"] / "result.txt"
    original = source.read_bytes()
    source.write_bytes(b"mutated after validation\n")
    with pytest.raises(V.Refusal, match="digest/mode"):
        V.publish(
            record_path=record_path, output_dir=case["output"],
            artifact="result.txt", destination=tmp_path / "refused.txt")
    source.write_bytes(original)
    destination = tmp_path / "sealed.txt"
    result = V.publish(
        record_path=record_path, output_dir=case["output"],
        artifact="result.txt", destination=destination)
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert destination.read_bytes() == original
    assert stat_mode(destination) == 0o600


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_publish_refuses_symlink_and_hardlink_artifacts(tmp_path, link_kind):
    case = _pytest_case(tmp_path)
    record_path = tmp_path / "validation.json"
    V.write_record(record_path, V.validate(**_validate_kwargs(case)))
    source = case["output"] / "result.txt"
    if link_kind == "symlink":
        saved = tmp_path / "saved-result.txt"
        source.replace(saved)
        source.symlink_to(saved)
    else:
        os.link(source, tmp_path / "second-link.txt")
    with pytest.raises(V.Refusal, match="symlink|single-link"):
        V.publish(
            record_path=record_path, output_dir=case["output"],
            artifact="result.txt", destination=tmp_path / "refused.txt")


def test_validation_record_itself_must_be_single_link_regular(tmp_path):
    case = _pytest_case(tmp_path)
    record_path = tmp_path / "validation.json"
    V.write_record(record_path, V.validate(**_validate_kwargs(case)))
    linked = tmp_path / "linked-validation.json"
    os.link(record_path, linked)
    with pytest.raises(V.Refusal, match="single-link"):
        V.strict_load_record(record_path)
    linked.unlink()
    symlink = tmp_path / "symlink-validation.json"
    symlink.symlink_to(record_path)
    with pytest.raises(V.Refusal, match="single-link"):
        V.strict_load_record(symlink)


@pytest.mark.parametrize(
    "raw,match",
    [
        (b'{"schema":1,"schema":1}\n', "duplicate"),
        (b'{"schema":NaN}\n', "non-finite"),
    ],
)
def test_validation_record_duplicate_keys_and_nan_refuse(tmp_path, raw, match):
    record = tmp_path / "ambiguous.json"
    record.write_bytes(raw)
    with pytest.raises(V.Refusal, match=match):
        V.strict_load_record(record)


def test_publish_destination_is_new_o_excl_boundary(tmp_path):
    case = _pytest_case(tmp_path)
    record_path = tmp_path / "validation.json"
    V.write_record(record_path, V.validate(**_validate_kwargs(case)))
    destination = tmp_path / "already-there.txt"
    destination.write_text("parent data\n", encoding="utf-8")
    with pytest.raises(V.Refusal, match="already exists"):
        V.publish(
            record_path=record_path, output_dir=case["output"],
            artifact="result.txt", destination=destination)
    assert destination.read_text(encoding="utf-8") == "parent data\n"
