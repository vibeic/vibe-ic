"""The short-deadline rule, driven in both directions.

ADVISORY by design, so the red is proved through `--strict`.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "wall_clock_bound_standing_in_for_a_verdict.py")

#: The defect: a sub-second forward-progress bound on a subject that spawns a
#: process, killed and reported as a substantive finding, saying nothing about
#: the load it fired under.
_DEFECT = '''\
import subprocess
import time


def drive(argv):
    proc = subprocess.Popen(argv)
    started = time.monotonic()
    while proc.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed > 0.45:
            proc.kill()
            raise AssertionError("did not advance for > 0.45s — killed as hung, "
                                 "not slow")
    return proc.returncode
'''

#: The same bound, carrying what makes it a measurement.
_REPAIRED = '''\
import os
import subprocess
import time


def drive(argv):
    """The 0.45 s bound was chosen at load average 2.9 on an idle host."""
    proc = subprocess.Popen(argv)
    started = time.monotonic()
    while proc.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed > 0.45:
            proc.kill()
            raise AssertionError(
                f"no progress in {elapsed:.2f}s at load {os.getloadavg()[0]:.1f}")
    return proc.returncode
'''

#: The OPPOSITE polarity: asserting a delay really happened. Under load this
#: passes more easily, not less. All eight sites the first sweep returned were
#: this shape, and none of them is the defect.
_LOWER_BOUND = '''\
import subprocess
import time


def test_the_sleep_really_slept():
    started = time.monotonic()
    subprocess.run(["true"])
    elapsed = time.monotonic() - started
    assert elapsed > 0.8, elapsed
'''

#: A short bound in a module that cannot spawn anything is nobody's business.
_NO_SPAWN = '''\
import time


def quick():
    t = time.monotonic()
    work()
    assert time.monotonic() - t < 0.45


def work():
    return 1
'''


def _tree(body: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="wcb_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "sample_driver.py").write_text(body)
    return root


def _run(root: Path, *extra):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), *extra],
        capture_output=True, text=True)


def test_a_sub_second_deadline_reported_as_a_finding_is_refused():
    """NEGATIVE CONTROL, via --strict."""
    r = _run(_tree(_DEFECT), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "0.45 s" in r.stdout


def test_the_same_site_is_advisory_by_default():
    r = _run(_tree(_DEFECT))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[WARN]" in r.stdout
    assert "interleave" in r.stdout, (
        "the remedy for a two-arm comparison must be in the message")


def test_a_bound_that_states_the_load_is_not_refused():
    r = _run(_tree(_REPAIRED), "--strict")
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_the_opposite_polarity_is_not_refused():
    """`elapsed > N` fires when the work was too FAST. Not this defect."""
    r = _run(_tree(_LOWER_BOUND), "--strict")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_module_that_cannot_spawn_is_out_of_population():
    r = _run(_tree(_NO_SPAWN), "--strict")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_floor_is_a_parameter_not_a_truth():
    """The predicate is the bound PLUS the subject, not the number."""
    root = _tree(_DEFECT)
    assert _run(root, "--strict", "--floor", "0.4").returncode == 0
    assert _run(root, "--strict", "--floor", "0.5").returncode == 1


def test_a_non_positive_floor_is_undetermined_not_a_pass():
    r = _run(_tree(_DEFECT), "--floor", "0")
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_runs_advisory_and_states_its_denominator():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "modules that spawn:" in r.stdout


def test_an_empty_population_is_undetermined_not_a_pass():
    """A GREEN FROM AN EMPTY DENOMINATOR IS NOT A PASS.

    Measured before the guard existed: on a well-formed but EMPTY tree this
    program printed its populations as 0 and then a `[PASS]` sentence that is a
    universal claim over the empty set -- vacuously true, and indistinguishable
    to a caller from the same sentence over the real repository.

    `gate_zero_denominator_refuses_check` refuses this shape, and CANNOT SEE
    THIS FILE: its population is `*_check.py`. So the refusal is asserted here.
    """
    root = Path(tempfile.mkdtemp(prefix="zeropop_"))
    try:
        (root / ".git").mkdir()
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "tests").mkdir(parents=True)
        r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 2, (
            f"an empty population returned rc={r.returncode}; it must be "
            f"UNDETERMINED, not a pass\n{r.stdout}")
        assert "NOT a pass" in r.stdout, r.stdout
        assert "[PASS]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
