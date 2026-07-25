#!/usr/bin/env python3
"""Bidirectional controls for program_test_coverage_check.

The check exists to stop a program landing without a test. Shipping it without one
would be self-refuting, so it carries its own — and by carrying one it removes itself
from the grandfather list, which is the behaviour it asks of everyone else.

Every case below builds a throwaway plugin tree on disk rather than pointing at the
real repo, so the controls stay valid as the real tree changes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parents[1] / "program_test_coverage_check.py"


def _tree(tmp: Path, programs: dict[str, str], tests: dict[str, str],
          baseline: list[str] | None = None, baseline_commit: str = "deadbee") -> Path:
    """Build a minimal programs/ + programs/tests/ tree."""
    p = tmp / "programs"
    (p / "tests").mkdir(parents=True)
    for name, body in programs.items():
        (p / name).write_text(body, encoding="utf-8")
    for name, body in tests.items():
        (p / "tests" / name).write_text(body, encoding="utf-8")
    if baseline is not None:
        lines = [f"# baseline-commit: {baseline_commit}", "#"] + baseline
        (p / "_test_coverage_baseline.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


def _run(root: Path):
    r = subprocess.run([sys.executable, str(CHECK), str(root), "--json"],
                       capture_output=True, text=True)
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError:
        payload = {}
    return r.returncode, payload, r.stdout + r.stderr


def test_check_is_executable_and_self_describing():
    assert CHECK.is_file(), f"check missing at {CHECK}"
    body = CHECK.read_text(encoding="utf-8")
    assert "BLOCKING" in body, "the check must state whether it blocks (flow-change-acceptance §5)"


def test_fires_on_a_new_program_with_no_test(tmp_path):
    """THE load-bearing control: an untested NEW program must FAIL the gate."""
    root = _tree(
        tmp_path,
        programs={"brand_new_thing.py": "x = 1\n"},
        tests={"test_unrelated.py": "def test_ok():\n    assert True\n"},
        baseline=[],
    )
    rc, out, _ = _run(root)
    assert rc == 1, "an untested new program must make the gate fail"
    assert out.get("verdict") == "FAIL"
    assert "brand_new_thing" in out.get("new_uncovered", [])


def test_passes_when_that_same_program_gains_a_test(tmp_path):
    """Paired with the control above — on its own this proves nothing.

    A gate that passes here but does NOT fail in the test above would be a rubber
    stamp; the two only mean something together.
    """
    root = _tree(
        tmp_path,
        programs={"brand_new_thing.py": "x = 1\n"},
        tests={"test_brand_new_thing.py": "def test_ok():\n    assert True\n"},
        baseline=[],
    )
    rc, out, _ = _run(root)
    assert rc == 0, "a program with a test must pass"
    assert out.get("new_uncovered") == []


def test_coverage_counts_a_mention_inside_a_test_body(tmp_path):
    """Coverage is deliberately generous: an import counts, not just a filename."""
    root = _tree(
        tmp_path,
        programs={"some_helper.py": "x = 1\n"},
        tests={"test_misc.py": "import some_helper\n\ndef test_ok():\n    assert True\n"},
        baseline=[],
    )
    rc, out, _ = _run(root)
    assert rc == 0, "a program imported by a test is exercised and must count as covered"


def test_grandfathered_program_does_not_fire(tmp_path):
    """Pre-existing untested programs must stay silent — a gate that is noise on day
    one is a gate people learn to ignore."""
    root = _tree(
        tmp_path,
        programs={"legacy_generator.py": "x = 1\n"},
        tests={"test_unrelated.py": "def test_ok():\n    assert True\n"},
        baseline=["legacy_generator"],
    )
    rc, out, _ = _run(root)
    assert rc == 0, "a grandfathered program must not fire"
    assert out.get("grandfathered") == 1


def test_grandfathering_does_not_hide_a_different_new_program(tmp_path):
    """The allowlist must exempt exactly what it names and nothing else."""
    root = _tree(
        tmp_path,
        programs={"legacy_generator.py": "x = 1\n", "brand_new_thing.py": "x = 1\n"},
        tests={"test_unrelated.py": "def test_ok():\n    assert True\n"},
        baseline=["legacy_generator"],
    )
    rc, out, _ = _run(root)
    assert rc == 1
    assert out.get("new_uncovered") == ["brand_new_thing"], (
        "the allowlist leaked past the name it declares"
    )


def test_reports_stale_baseline_entries_so_the_list_shrinks(tmp_path):
    """An entry that has since gained a test must be surfaced for removal.

    Without this the list rots: it would keep claiming coverage debt that no longer
    exists, and nobody would ever prune it.
    """
    root = _tree(
        tmp_path,
        programs={"legacy_generator.py": "x = 1\n"},
        tests={"test_legacy_generator.py": "def test_ok():\n    assert True\n"},
        baseline=["legacy_generator"],
    )
    rc, out, _ = _run(root)
    assert rc == 0
    assert out.get("stale_baseline_entries") == ["legacy_generator"]


def test_underscore_private_modules_are_not_required_to_have_tests(tmp_path):
    root = _tree(
        tmp_path,
        programs={"_internal_helper.py": "x = 1\n"},
        tests={"test_unrelated.py": "def test_ok():\n    assert True\n"},
        baseline=[],
    )
    rc, out, _ = _run(root)
    assert rc == 0
    assert out.get("programs_total") == 0


def test_missing_tests_dir_is_an_error_not_a_silent_pass(tmp_path):
    """Degrade loudly, never silently (flow-change-acceptance §6).

    If the tree is not what the check expects, it must say so rather than report a
    clean bill of health it never earned.
    """
    (tmp_path / "programs").mkdir()
    rc, _, text = _run(tmp_path)
    assert rc == 2, "a malformed tree must be an error, not a pass"
    assert "no programs/tests" in text


def test_declares_blocking_in_its_json(tmp_path):
    root = _tree(tmp_path, programs={"a.py": "x=1\n"},
                 tests={"test_a.py": "def test_ok():\n    assert True\n"}, baseline=[])
    _, out, _ = _run(root)
    assert out.get("blocks") is True, (
        "the gate must declare BLOCKING vs ADVISORY in its own output, not leave it "
        "to be inferred"
    )
