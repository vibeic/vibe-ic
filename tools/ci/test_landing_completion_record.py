from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "landing_completion_record", HERE / "landing_completion_record.py")
assert SPEC and SPEC.loader
C = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = C
SPEC.loader.exec_module(C)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Completion Test")
    _git(repo, "config", "user.email", "completion@example.test")
    (repo / "tracked.txt").write_text("subject\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "subject")
    return repo, _git(repo, "rev-parse", "HEAD")


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    selection = tmp_path / "selection"
    plan = tmp_path / "progress-plan.json"
    hygiene = tmp_path / "hygiene.json"
    selection.write_text("programs/tests/test_one.py\n", encoding="utf-8")
    plan.write_text('{"schema":1,"units":["one"]}\n', encoding="utf-8")
    hygiene.write_text('{"complete":true,"schema":1}\n', encoding="utf-8")
    return selection, plan, hygiene


def _environment(monkeypatch: pytest.MonkeyPatch, head: str) -> None:
    monkeypatch.setenv("GATEKEEPER_VERIFY_ARM", "A2")
    monkeypatch.setenv("GATEKEEPER_BASE", head)
    monkeypatch.setenv("GATEKEEPER_BENCHMARK_DATA_SHA", "b" * 40)
    monkeypatch.setenv("VIBEIC_LANDING_PROGRESS_NONCE", "c" * 64)


def _finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            *, failed: int = 0):
    repo, head = _repo(tmp_path)
    selection, plan, hygiene = _inputs(tmp_path)
    journal = tmp_path / "journal.json"
    _environment(monkeypatch, head)
    monkeypatch.chdir(repo)
    for index, label in enumerate(C.LANDING_PROGRESS_UNITS):
        state = "FAIL" if failed and index == 1 else (
            "SKIP" if index == 2 else "PASS")
        C.append(journal, label=label, state=state,
                 returncode=1 if state == "FAIL" else 0,
                 output_sha256=f"{index % 16:x}" * 64)
    record = C.finish(
        journal, failed=failed, selection_path=selection,
        progress_plan_path=plan, hygiene_path=hygiene)
    return record, journal


def test_append_finish_and_strict_round_trip(tmp_path, monkeypatch):
    record, journal = _finish(tmp_path, monkeypatch)
    assert oct(journal.stat().st_mode & 0o777) == "0o600"
    assert record["payload"]["arm"] == "A2"
    assert [row["label"] for row in record["payload"]["gates"]] == list(
        C.LANDING_PROGRESS_UNITS)
    assert record["payload"]["gates"][2]["state"] == "SKIP"
    assert record["payload"]["failed"] == 0
    assert record["payload"]["returncode"] == 0
    out = tmp_path / "completion.json"
    C._atomic_write(out, C.strict.canonical_bytes(record), replace=False)
    assert C.strict_load_record(out) == record


def test_hermetic_git_identity_is_exact_and_ambient_free(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, "a" * 40 + "\n", "")

    monkeypatch.setattr(C.subprocess, "run", fake_run)
    monkeypatch.setattr(C, "_resolved_cwd", lambda: Path("/subject"))
    monkeypatch.setenv("VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "99")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "include.path")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "attacker"))
    assert C._git("rev-parse", "HEAD^{commit}") == "a" * 40
    assert captured["env"]["GIT_CONFIG_COUNT"] == "1"
    assert captured["env"]["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert captured["env"]["GIT_CONFIG_VALUE_0"] == "/subject"
    assert captured["env"]["GIT_CONFIG_GLOBAL"] == os.devnull
    assert captured["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert captured["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_hermetic_completion_refuses_any_other_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY", "1")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(C.Refusal, match="exact /subject"):
        C._git("rev-parse", "HEAD^{commit}")


def test_failure_population_and_shell_flag_must_agree(tmp_path, monkeypatch):
    record, journal = _finish(tmp_path, monkeypatch, failed=1)
    assert record["payload"]["failed"] == 1
    assert record["payload"]["returncode"] == 1
    with pytest.raises(C.Refusal, match="FAILED flag disagrees"):
        C.finish(
            journal, failed=0,
            selection_path=tmp_path / "selection",
            progress_plan_path=tmp_path / "progress-plan.json",
            hygiene_path=tmp_path / "hygiene.json")


def test_duplicate_label_and_state_returncode_laundering_refuse(
        tmp_path, monkeypatch):
    journal = tmp_path / "journal.json"
    first = C.LANDING_PROGRESS_UNITS[0]
    C.append(journal, label=first, state="PASS", returncode=0,
             output_sha256="a" * 64)
    with pytest.raises(C.Refusal, match="next parent-owned"):
        C.append(journal, label=first, state="PASS", returncode=0,
                 output_sha256="b" * 64)
    for state, rc in (("PASS", 1), ("FAIL", 0), ("SKIP", 2)):
        with pytest.raises(C.Refusal, match="disagree"):
            C.append(tmp_path / f"{state}.json", label=first, state=state,
                     returncode=rc, output_sha256="c" * 64)
    with pytest.raises(C.Refusal, match="malformed"):
        C.append(tmp_path / "bool.json", label=first, state="PASS",
                 returncode=True, output_sha256="d" * 64)


def test_report_state_retains_nonblocking_raw_returncode(tmp_path):
    journal = tmp_path / "journal.json"
    C.append(journal, label=C.LANDING_PROGRESS_UNITS[0], state="REPORT",
             returncode=17, output_sha256="a" * 64)
    assert C._journal(journal)[0]["returncode"] == 17


def test_record_parser_rejects_semantic_extra_duplicate_and_nonfinite(
        tmp_path, monkeypatch):
    record, _ = _finish(tmp_path, monkeypatch)
    bad = json.loads(json.dumps(record))
    bad["payload"]["gates"][0]["state"] = "FAIL"
    bad["payload"]["gates"][0]["returncode"] = 0
    bad["payload_sha256"] = hashlib.sha256(
        C.strict.canonical_bytes(bad["payload"])).hexdigest()
    with pytest.raises(C.Refusal, match="state/returncode"):
        C.parse_record(bad)

    reordered = json.loads(json.dumps(record))
    reordered["payload"]["gates"][0]["label"] = "forged"
    reordered["payload_sha256"] = hashlib.sha256(
        C.strict.canonical_bytes(reordered["payload"])).hexdigest()
    with pytest.raises(C.Refusal, match="population"):
        C.parse_record(reordered)

    extra = json.loads(json.dumps(record))
    extra["payload"]["extra"] = False
    extra["payload_sha256"] = hashlib.sha256(
        C.strict.canonical_bytes(extra["payload"])).hexdigest()
    with pytest.raises(C.Refusal, match="wrong schema"):
        C.parse_record(extra)

    out = tmp_path / "ambiguous.json"
    out.write_bytes(b'{"schema":1,"schema":1}\n')
    with pytest.raises(C.Refusal, match="duplicate"):
        C.strict_load_record(out)
    out.write_bytes(b'{"schema":NaN}\n')
    with pytest.raises(C.Refusal, match="non-finite"):
        C.strict_load_record(out)


def test_evidence_files_must_be_single_link_regular_files(tmp_path, monkeypatch):
    record, journal = _finish(tmp_path, monkeypatch)
    del record
    linked = tmp_path / "journal-linked.json"
    os.link(journal, linked)
    with pytest.raises(C.Refusal, match="single-link"):
        C._journal(journal)
    journal.unlink()
    linked.unlink()

    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    symlink = tmp_path / "completion.json"
    symlink.symlink_to(target)
    with pytest.raises(C.Refusal, match="regular file"):
        C.strict_load_record(symlink)


def test_parent_plan_is_exact_finite_population(tmp_path):
    out = tmp_path / "plan.json"
    assert C.main([
        "plan", "--scope", "landing:A2", "--stall-grace-seconds", "300",
        "--output", str(out),
    ]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "schema": 1,
        "scope": "landing:A2",
        "stall_grace_seconds": 300,
        "units": list(C.LANDING_PROGRESS_UNITS),
    }
