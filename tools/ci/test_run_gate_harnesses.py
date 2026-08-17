"""The sweeper that fires the colocated gate harnesses must itself be fireable.

This file is PYTEST and lives under `tools/`, so it is executed by the gate that
already exists for repo-level tests (`gatekeeper-land.sh::run_repo_tools_pytest`,
guarded by `tools/ci/test_repo_tools_tests_gate.py`).  The thing it tests is
bash, and bash under `tools/ci/` is exactly what was running nowhere — so the
guard is deliberately written in the language that already has a runner rather
than adding a fourth harness to the set nothing swept.

BOTH DIRECTIONS FOR EVERY CASE.  A sweeper is the easiest check in the world to
write so it cannot fail: point it at a directory, run whatever is there, exit 0.
Each case therefore pairs the outcome that must be GREEN with the outcome that
must be RED, and the empty sweep — the one that turns the whole feature off
silently — is asserted to be a REFUSAL rather than either.
"""
import subprocess
import textwrap
from pathlib import Path

_SWEEPER = Path(__file__).resolve().parent / "run_gate_harnesses.sh"


def _sweep(directory):
    return subprocess.run(["bash", str(_SWEEPER), str(directory)],
                          capture_output=True, text=True)


def _harness(directory, name, body):
    path = directory / name
    path.write_text(textwrap.dedent(body))
    path.chmod(0o755)
    return path


def test_the_sweeper_ships_with_the_repo():
    assert _SWEEPER.is_file(), f"{_SWEEPER} is missing"


def test_all_green_harnesses_pass_and_the_denominator_is_printed(tmp_path):
    """CAN PASS."""
    _harness(tmp_path, "test_a.sh", "#!/usr/bin/env bash\nexit 0\n")
    _harness(tmp_path, "test_b.sh", "#!/usr/bin/env bash\nexit 0\n")
    out = _sweep(tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    # The COUNT, not just the word "passed": a sweep that stops discovering
    # must not be able to print the same reassuring sentence.
    assert "2 discovered harness(es) passed" in out.stdout


def test_one_red_harness_fails_the_sweep_and_is_named(tmp_path):
    """CAN FAIL — and the failure has to be attributable."""
    _harness(tmp_path, "test_a.sh", "#!/usr/bin/env bash\nexit 0\n")
    _harness(tmp_path, "test_b.sh", "#!/usr/bin/env bash\nexit 3\n")
    out = _sweep(tmp_path)
    combined = out.stdout + out.stderr
    assert out.returncode == 1, combined
    assert "test_b.sh" in combined
    # The exit status is carried, for the same reason `_gate_outcome_facts`
    # exists one level down: "it failed" and "it could not start" are different
    # instructions to the reader.
    assert "exit 3" in combined
    assert "test_a.sh (exit" not in combined


def test_an_empty_sweep_is_a_refusal_not_a_pass(tmp_path):
    """THE LOAD-BEARING CASE: discovering nothing must never read as clean."""
    out = _sweep(tmp_path)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "DISCOVERED NOTHING" in out.stderr
    assert "[PASS]" not in out.stdout


def test_a_directory_that_does_not_exist_is_a_refusal(tmp_path):
    out = _sweep(tmp_path / "absent")
    assert out.returncode == 2, out.stdout + out.stderr


def test_non_harness_files_are_not_swept(tmp_path):
    """A scope that is too WIDE is its own defect: the sweep must not run the
    dispatcher library itself, or a helper, just because it lives here."""
    _harness(tmp_path, "test_a.sh", "#!/usr/bin/env bash\nexit 0\n")
    _harness(tmp_path, "_helper.sh", "#!/usr/bin/env bash\nexit 9\n")
    _harness(tmp_path, "run_something.sh", "#!/usr/bin/env bash\nexit 9\n")
    out = _sweep(tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 discovered harness(es) passed" in out.stdout


def test_the_real_directory_discovers_the_shipped_harnesses():
    """The probe must be able to FIRE on the real tree, not only on fixtures.

    Discovery only — running them is the gate's job, and doing it here would
    make this fast pytest file as slow as the harnesses it is about.
    """
    shipped = sorted(p.name for p in _SWEEPER.parent.glob("test_*.sh"))
    assert len(shipped) >= 3, shipped
    assert "test_gate_scope.sh" in shipped
    assert "test_gate_concurrency.sh" in shipped
