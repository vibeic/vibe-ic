"""Unit tests for benchmark_setup.py — the env-check + dataset-clone helper that
backs /vibe-ic-benchmark.

Pure-stdlib, NO network: the benchmark registry is a local JSON file and every
external action (git clone, HuggingFace download) is only *printed*, never run.
Tool probing (iverilog/yosys/docker/git/mcp) is exercised by monkeypatching
``shutil.which`` / ``subprocess`` so the suite is host-independent.

Covers:
  * env_summary() returns the documented key set and degrades gracefully (all
    False, no crash) when every probed tool is absent;
  * the --print-clone path prints the documented command for each dataset kind
    (git repo / HuggingFace / internal) of a KNOWN registry benchmark;
  * unknown-benchmark handling raises a clean SystemExit (a message, not a crash).
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "benchmark_setup.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import benchmark_setup as bs  # noqa: E402


# --------------------------------------------------------------------------- #
# env_summary() — keys + graceful degradation
# --------------------------------------------------------------------------- #
EXPECTED_ENV_KEYS = {
    "iverilog", "yosys", "docker", "iic_eda_running",
    "mcp_server_alive", "git", "python3",
}


def test_env_summary_has_all_documented_keys():
    env = bs.env_summary()
    assert isinstance(env, dict)
    assert set(env) == EXPECTED_ENV_KEYS
    # every value is a plain bool (so the [OK]/[  ] renderer can't blow up)
    assert all(isinstance(v, bool) for v in env.values())


def test_env_summary_degrades_gracefully_when_no_tools(monkeypatch):
    """When NOTHING is on PATH, env_summary must still return the full key set,
    all False, and must not raise (the docker/mcp probes are guarded by _has)."""
    # No executable resolves -> _has() is False for everything, which also
    # short-circuits _docker_ps()/_mcp_alive() before they shell out.
    monkeypatch.setattr(bs.shutil, "which", lambda _cmd: None)

    def _boom(*_a, **_k):  # pragma: no cover - asserts the guards prevent this
        raise AssertionError("subprocess must not run when no tools are present")

    monkeypatch.setattr(bs.subprocess, "run", _boom)

    env = bs.env_summary()
    assert set(env) == EXPECTED_ENV_KEYS
    assert env == {k: False for k in EXPECTED_ENV_KEYS}


def test_env_summary_reflects_present_tools(monkeypatch):
    """A tool that resolves on PATH shows up True; the container/mcp probes that
    depend on a missing tool stay False."""
    present = {"iverilog", "yosys", "git", "python3"}
    monkeypatch.setattr(bs.shutil, "which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in present else None)
    # docker absent -> _docker_ps() returns empty set without shelling out;
    # pgrep absent -> _mcp_alive() returns False without shelling out.
    monkeypatch.setattr(bs.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no subprocess expected here")))
    env = bs.env_summary()
    assert env["iverilog"] is True and env["yosys"] is True
    assert env["git"] is True and env["python3"] is True
    assert env["docker"] is False
    assert env["iic_eda_running"] is False
    assert env["mcp_server_alive"] is False


# --------------------------------------------------------------------------- #
# --print-clone — dataset-clone-command path (no network; just prints)
# --------------------------------------------------------------------------- #
def _run_main(argv, monkeypatch):
    """Invoke main() with a fixed argv. Keep tool-probing host-independent."""
    monkeypatch.setattr(bs.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(sys, "argv", ["benchmark_setup.py", *argv])
    return bs.main()


def test_print_clone_git_repo_benchmark(capsys, monkeypatch):
    # rtllm ships a public git repo dataset (MIT). The documented form is a
    # `git clone <repo>` line annotated with the license — and NEVER auto-runs.
    rv = _run_main(["rtllm", "--print-clone"], monkeypatch)
    out = capsys.readouterr().out
    assert rv is None  # clean return, no SystemExit
    assert out.startswith("git clone ")
    assert "https://github.com/hkust-zhiyao/RTLLM" in out
    assert "license: MIT" in out


def test_print_clone_huggingface_benchmark(capsys, monkeypatch):
    # rtl-repo has only a HuggingFace dataset; the documented form prints the
    # load_dataset(...).save_to_disk(...) recipe (commented, never executed).
    _run_main(["rtl-repo", "--print-clone"], monkeypatch)
    out = capsys.readouterr().out
    assert "HuggingFace dataset: ahmedallam/RTL-Repo" in out
    assert "pip install datasets" in out
    assert "load_dataset('ahmedallam/RTL-Repo'" in out
    assert "save_to_disk('./rtl-repo_data')" in out


def test_print_clone_internal_benchmark(capsys, monkeypatch):
    # benchmark_clean is internal (no external dataset) -> documented no-op note.
    _run_main(["benchmark_clean", "--print-clone"], monkeypatch)
    out = capsys.readouterr().out
    assert "no external dataset" in out


def test_print_clone_never_emits_a_runnable_clone_for_internal(capsys, monkeypatch):
    # Defensive: the internal benchmark must NOT print an executable `git clone`.
    _run_main(["benchmark_clean", "--print-clone"], monkeypatch)
    out = capsys.readouterr().out
    assert not out.strip().startswith("git clone ")


# --------------------------------------------------------------------------- #
# unknown-benchmark handling — clean error, not a crash
# --------------------------------------------------------------------------- #
def test_unknown_benchmark_raises_clean_systemexit(monkeypatch):
    monkeypatch.setattr(bs.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(sys, "argv",
                        ["benchmark_setup.py", "definitely-not-a-real-benchmark",
                         "--print-clone"])
    with pytest.raises(SystemExit) as ei:
        bs.main()
    # SystemExit carries the human message (truthy, non-zero) — not a bare crash.
    assert ei.value.code != 0
    assert "Unknown benchmark" in str(ei.value.code)


def test_unknown_benchmark_without_print_clone_also_errors(monkeypatch):
    # The unknown-name guard fires before --print-clone is consulted.
    monkeypatch.setattr(bs.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(sys, "argv",
                        ["benchmark_setup.py", "no-such-benchmark"])
    with pytest.raises(SystemExit) as ei:
        bs.main()
    assert "Unknown benchmark 'no-such-benchmark'" in str(ei.value.code)
