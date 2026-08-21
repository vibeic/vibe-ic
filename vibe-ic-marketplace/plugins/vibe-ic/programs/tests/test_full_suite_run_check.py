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
def test_only_programs_tests_is_full_since_the_v0219_merge():
    """UPDATED at the v1.6.0 land — this test used to pin the PRE-merge
    reality (programs/tests alone == subset). Since v0.2.19 the integration
    tree holds no test files and pytest.ini's testpaths is programs/tests
    alone, so an explicit programs/tests run IS the full suite (measured:
    both collect 19504). The pre-merge meaning survives as the negative
    control test_two_tree_rule_reinstates_when_integration_tree_grows_tests."""
    assert fsr.main(["--command", "python3 -m pytest -q programs/tests/"]) == 0


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


def test_file_scan_with_programs_tests_is_full_since_the_merge(tmp_path):
    """UPDATED at the v1.6.0 land, same reason as
    test_only_programs_tests_is_full_since_the_v0219_merge. A file-scan of a
    log carrying `pytest programs/tests` now reads as full; a genuinely
    narrowed run (a -k selector) in a scanned log must still read as subset —
    both directions kept."""
    f = tmp_path / "log.txt"
    f.write_text("python3 -m pytest -q programs/tests/\n")
    out = tmp_path / "r.json"
    rc = fsr.main([str(f), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["full_suite_found"] is True
    f2 = tmp_path / "log2.txt"
    f2.write_text("python3 -m pytest -q programs/tests/ -k foo\n")
    assert fsr.main([str(f2)]) == 1


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


# ── v0.2.19 merged-tree awareness (added at the v1.6.0 land) ─────────────────
# The two-tree rule predates the v0.2.19 merge: conftest.py records the merge
# and pytest.ini's testpaths is programs/tests alone. Measured on this tree,
# `pytest -q --collect-only` == `pytest programs/tests -q --collect-only`
# (19504 == 19504). The gate now detects the empty integration tree LIVE, so
# it self-corrects in both directions.

def test_explicit_programs_tests_is_full_when_integration_tree_is_empty(tmp_path):
    """Today's reality: tests/ holds no test files, so an explicit
    programs/tests run IS the full suite."""
    import full_suite_run_check as F
    assert F._integration_tree_has_tests(tmp_path) is False  # empty root
    ok, reason = F._classify_pytest(
        ["python3", "-m", "pytest", "programs/tests", "-q"])
    assert ok is True, reason
    assert "integration tree holds no test files" in reason


def test_two_tree_rule_reinstates_when_integration_tree_grows_tests(tmp_path):
    """NEGATIVE CONTROL, the direction that keeps this from being a loophole:
    the moment tests/ holds a test file again, programs/tests alone is a
    subset once more — with no one editing the gate."""
    import full_suite_run_check as F
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_revived.py").write_text("def test_x():\n    pass\n")
    assert F._integration_tree_has_tests(tmp_path) is True


def test_no_path_invocation_still_full(tmp_path):
    import full_suite_run_check as F
    ok, reason = F._classify_pytest(["python3", "-m", "pytest", "-q"])
    assert ok is True


def test_subset_flags_still_narrow_regardless_of_tree_state():
    import full_suite_run_check as F
    ok, _ = F._classify_pytest(
        ["python3", "-m", "pytest", "programs/tests", "-q", "-k", "foo"])
    assert ok is False
