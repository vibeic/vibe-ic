from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "_tested_hermetic_git_subject", HERE / "hermetic_git_subject.py")
assert SPEC is not None and SPEC.loader is not None
H = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = H
SPEC.loader.exec_module(H)


def _run(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          text=True, stdout=subprocess.PIPE)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.name", "test")
    _run(repo, "config", "user.email", "test@example.invalid")
    (repo / "plain.txt").write_bytes(b"raw\r\nbytes\n")
    executable = repo / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    _run(repo, "add", ".")
    _run(repo, "commit", "-qm", "one")
    return repo, _run(repo, "rev-parse", "HEAD")


def test_materializes_raw_self_contained_clean_repository(tmp_path: Path) -> None:
    source, commit = _repo(tmp_path)
    output = tmp_path / "subject"
    record = H.materialize(source, commit, output)
    assert record["complete"] is True
    assert record["payload"]["commit"] == commit
    assert _run(output, "rev-parse", "HEAD") == commit
    assert _run(output, "status", "--porcelain=v1") == ""
    assert _run(output, "remote") == ""
    assert not (output / ".git" / "objects" / "info" / "alternates").exists()
    assert (output / "plain.txt").read_bytes() == b"raw\r\nbytes\n"
    assert stat.S_IMODE((output / "run.sh").stat().st_mode) == 0o755


def test_output_is_container_readable_and_has_no_external_config(tmp_path: Path) -> None:
    source, commit = _repo(tmp_path)
    output = tmp_path / "subject"
    H.materialize(source, commit, output)
    for root, directories, files in os.walk(output):
        assert stat.S_IMODE(Path(root).stat().st_mode) & 0o005 == 0o005
        for name in files:
            assert stat.S_IMODE((Path(root) / name).stat().st_mode) & 0o004
    config = (output / ".git" / "config").read_text()
    assert "remote" not in config
    assert "hooksPath = /dev/null" in config


def test_refuses_symlink_and_gitlink_population(tmp_path: Path) -> None:
    source, commit = _repo(tmp_path)
    (source / "link").symlink_to("plain.txt")
    _run(source, "add", "link")
    _run(source, "commit", "-qm", "link")
    try:
        H.materialize(source, _run(source, "rev-parse", "HEAD"),
                      tmp_path / "subject")
    except H.Refusal as exc:
        assert "unsupported tracked mode" in str(exc)
    else:
        raise AssertionError("tracked symlink was accepted")


def test_cli_writes_canonical_private_record(tmp_path: Path) -> None:
    source, commit = _repo(tmp_path)
    output = tmp_path / "subject"
    record = tmp_path / "record.json"
    assert H.main(["--object-repo", str(source), "--commit", commit,
                   "--output", str(output), "--record", str(record)]) == 0
    raw = record.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert json.loads(raw)["payload"]["commit"] == commit
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
