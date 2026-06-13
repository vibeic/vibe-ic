#!/usr/bin/env python3
"""Tests for full_suite_run_check.py — verify the core-agent ran the FULL
pytest suite (both trees), not a subset (chip-AGNOSTIC)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "full_suite_run_check.py"
_spec = importlib.util.spec_from_file_location("full_suite_run_check", _PROG)
fsr = importlib.util.module_from_spec(_spec)
sys.modules["full_suite_run_check"] = fsr
_spec.loader.exec_module(fsr)


# ---- PASS cases ---------------------------------------------------------
def test_pass_no_path_filter():
    assert fsr.main(["--command", "python3 -m pytest -q"]) == 0


def test_pass_bare_pytest():
    assert fsr.main(["--command", "pytest"]) == 0


def test_pass_both_trees_explicit():
    assert fsr.main(["--command", "python3 -m pytest -q programs/tests tests"]) == 0


def test_pass_cd_then_pytest_chain():
    # `cd $ROOT && python3 -m pytest -q` — the canonical Step-3 command.
    assert fsr.main(["--command",
                     "cd /plugin && python3 -m pytest -q"]) == 0


def test_pass_import_mode_value_flag_not_a_path():
    assert fsr.main(["--command",
                     "python3 -m pytest -q -p no:cacheprovider"]) == 0


# ---- FAIL cases ---------------------------------------------------------
def test_fail_only_programs_tests():
    assert fsr.main(["--command", "python3 -m pytest -q programs/tests/"]) == 1


def test_fail_only_integration_tests():
    assert fsr.main(["--command", "pytest tests/"]) == 1


def test_fail_single_file():
    assert fsr.main(["--command", "pytest tests/test_compliance.py"]) == 1


def test_fail_k_selector():
    assert fsr.main(["--command", "python3 -m pytest -q -k version"]) == 1


def test_fail_no_pytest_at_all():
    # the suite was never run -> honest FAIL (not vacuous PASS).
    assert fsr.main(["--command", "git push origin main"]) == 1


# ---- file scan + JSON + edge --------------------------------------------
def test_file_scan_subset_then_full(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(
        "python3 -m pytest -q programs/tests/\n"   # subset
        "python3 -m pytest -q\n"                    # full — rescues it
    )
    out = tmp_path / "r.json"
    rc = fsr.main([str(f), "--json", str(out)])
    assert rc == 0   # a full-suite run is present anywhere => PASS
    rep = json.loads(out.read_text())
    assert rep["full_suite_found"] is True
    assert rep["pytest_invocations"] == 2


def test_file_scan_only_subset_fails(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text("python3 -m pytest -q programs/tests/\n")
    out = tmp_path / "r.json"
    rc = fsr.main([str(f), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["full_suite_found"] is False
    assert rep["invocations"][0]["full_suite"] is False


def test_empty_input_is_honest_fail(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("\n# nothing\n")
    rc = fsr.main([str(f)])
    # no pytest seen => the suite was NOT run => FAIL, never vacuous PASS.
    assert rc == 1


def test_missing_file_is_error(tmp_path):
    assert fsr.main([str(tmp_path / "nope.txt")]) == 2


def test_no_args_is_error():
    assert fsr.main([]) == 2
