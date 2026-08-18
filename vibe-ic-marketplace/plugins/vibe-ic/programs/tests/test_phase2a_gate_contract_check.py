"""Tests for phase1_gate_contract_check.py — meta-checker for Phase-2a gates."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "phase1_gate_contract_check.py"
PROGRAMS_DIR = Path(__file__).parent.parent


def _private_plugin(tmp_path: Path) -> tuple[Path, Path]:
    """A private plugin tree the checker can be run FROM, with a real flow.

    THE FAKE GATES USED TO BE WRITTEN INTO THE LIVE `programs/` DIR. Each of
    the three tests below planted a `__fake_gate_*__.py` beside the shipped
    programs for the duration of its body and unlinked it in a `finally`.
    Serially nothing sees it; the landing gate's per-file parallel path runs one
    pytest session per file over ONE shared checkout, so every concurrent
    session that enumerates `programs/` counted the fakes as programs of this
    branch — and the fakes are built to violate the contract, so they are read
    as findings. Because the `finally` removes them, `git status --porcelain`
    is clean afterwards and the manufactured red has nothing to follow.

    `phase1_gate_contract_check` resolves everything it reads from its OWN
    location — `PROGRAMS_DIR = Path(__file__).parent`, `TESTS_DIR`, and
    `FLOW_YAML = PROGRAMS_DIR.parent / "flow" / ...`. So a copy of the program
    in a private `programs/` dir, with `flow/` symlinked to the real one, reads
    the SAME flow definition and the same contract rules while looking at a
    gate inventory this test owns. Nothing about what is being checked changes.
    """
    plugin = tmp_path / "plugin"
    progs = plugin / "programs"
    (progs / "tests").mkdir(parents=True)
    shutil.copy2(PROGRAM, progs / PROGRAM.name)
    (plugin / "flow").symlink_to(PROGRAMS_DIR.parent / "flow",
                                 target_is_directory=True)
    return progs, progs / PROGRAM.name


def _no_fake_gate_reached_the_live_tree():
    strays = sorted(p.name for p in PROGRAMS_DIR.glob("__fake_gate_*__.py"))
    assert not strays, (
        f"this test planted {strays} into the live programs dir; a concurrent "
        f"session enumerating programs/ would count them as the branch's")


def test_default_7_gates_pass():
    """The 7 gates shipped in v0.74 must all satisfy the contract."""
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"
    assert out["gates_checked"] == 7
    assert out["total_errors"] == 0


def test_missing_file_flagged(tmp_path, monkeypatch):
    """A non-existent gate name must be flagged as file_missing (error)."""
    r = subprocess.run(
        [sys.executable, str(PROGRAM),
         "--gates", "__nonexistent_gate_xyz__", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    out = json.loads(r.stdout)
    rules = [f["rule"] for f in out["findings"]]
    assert "file_missing" in rules


def test_fake_gate_missing_contract_clauses(tmp_path):
    """Create a fake gate that violates contract clauses, verify detection."""
    # Make a minimal gate that fails everything:
    # - No docstring → missing_docstring
    # - No --json in source → missing_json_flag
    # - No pytest file → missing_pytest
    # - Not in flow YAML → not_wired_into_flow
    progs, program = _private_plugin(tmp_path)
    fake_gate = progs / "__fake_gate_for_test__.py"
    fake_gate.write_text(textwrap.dedent("""
        import sys
        if __name__ == "__main__":
            sys.exit(0)
    """))
    try:
        r = subprocess.run(
            [sys.executable, str(program),
             "--gates", "__fake_gate_for_test__", "--json"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1
        out = json.loads(r.stdout)
        rules = [f["rule"] for f in out["findings"]]
        assert "missing_docstring" in rules
        assert "missing_json_flag" in rules
        assert "missing_pytest" in rules
        assert "not_wired_into_flow" in rules
    finally:
        _no_fake_gate_reached_the_live_tree()


def test_fake_gate_with_docstring_but_missing_sections(tmp_path):
    """Gate with docstring but no Usage/Exit-codes sections is flagged."""
    progs, program = _private_plugin(tmp_path)
    fake_gate = progs / "__fake_gate_sections_test__.py"
    fake_gate.write_text(textwrap.dedent('''
        """
        Minimal gate — intentionally missing required sections.
        """
        import argparse, sys
        if __name__ == "__main__":
            ap = argparse.ArgumentParser()
            ap.add_argument("--json", action="store_true")
            ap.parse_args()
            sys.exit(0)
    '''))
    try:
        r = subprocess.run(
            [sys.executable, str(program),
             "--gates", "__fake_gate_sections_test__", "--json"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1
        out = json.loads(r.stdout)
        rules = [f["rule"] for f in out["findings"]]
        assert "missing_usage_section" in rules
        assert "missing_exit_codes_section" in rules
    finally:
        _no_fake_gate_reached_the_live_tree()


def test_gate_without_help_flag_fails(tmp_path):
    """Gate whose --help returns nonzero is flagged."""
    progs, program = _private_plugin(tmp_path)
    fake_gate = progs / "__fake_gate_help_test__.py"
    fake_gate.write_text(textwrap.dedent('''
        """
        Minimal gate with broken --help.

        Usage
        -----
            __fake_gate_help_test__.py

        Exit codes
        ----------
            0 = pass
            1 = fail
            2 = io error
        """
        import sys
        if __name__ == "__main__":
            if "--help" in sys.argv:
                sys.exit(99)
            sys.exit(0)
    '''))
    try:
        r = subprocess.run(
            [sys.executable, str(program),
             "--gates", "__fake_gate_help_test__", "--json"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1
        out = json.loads(r.stdout)
        rules = [f["rule"] for f in out["findings"]]
        assert "help_nonzero" in rules
    finally:
        _no_fake_gate_reached_the_live_tree()


def test_empty_gates_list_errors():
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--gates", "", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_human_readable_output_has_summary():
    """Non-JSON output must end with PASS/FAIL summary line."""
    r = subprocess.run(
        [sys.executable, str(PROGRAM)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    last = r.stdout.strip().split("\n")[-1]
    assert last in ("PASS", "FAIL")


def test_each_gate_individually(tmp_path):
    """Run meta-check on each gate one at a time — all must PASS."""
    gates = [
        "internal_vs_external_timing_check",
        "rsp_example_otp_consistency_check",
        "threshold_range_contiguity_check",
        "spec_response_delay_check",
        "nba_addr_read_race_check",
        "periodic_timer_vs_rx_activity_check",
        "memory_read_pipeline_check",
    ]
    for g in gates:
        r = subprocess.run(
            [sys.executable, str(PROGRAM), "--gates", g, "--json"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"{g}: {r.stdout}"
        out = json.loads(r.stdout)
        assert out["total_errors"] == 0, f"{g}: {out}"
