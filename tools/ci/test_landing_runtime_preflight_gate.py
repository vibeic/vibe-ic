"""The landing must REFUSE ONCE when it cannot run the protected test runtime.

v1.10.69 routed all three landing arms through `trusted_pytest_entry.py` under
`python3 -I`. Isolated mode suppresses the USER site directory, so on a host
whose test runner lives only there the child dies before emitting one lifecycle
event. MEASURED on the landing host at 7c376e348, the repo-tools arm alone:

    asked 40  recorded 0  NORECORD 40  aggregate INCOMPLETE rc=2 cases=0

Across the three arms that is hundreds of UNKNOWN lines naming hundreds of
innocent files and not one line naming the cause. That is what this file guards
against coming back: the gate must say "I cannot look" ONCE, with the cause and
the remedy, and must not answer a question it could not ask.

WHY A SHIM INTERPRETER AND NOT THE HOST'S OWN
=============================================
The whole difficulty of testing this is that the condition under test is a
PROPERTY OF THE HOST. On this fleet `python3 -I` cannot import the runner, so a
test that just runs the preflight measures the host and would silently invert
inside the pinned image, where it can. Both directions would then be
host-dependent and neither would be a control.

So the interpreter is supplied. `<real python3> -S` keeps `sys.flags.isolated`
and `sys.flags.ignore_environment` set — the entry's own contract still holds —
while removing every site directory, which makes "the isolated interpreter
cannot import the runner" TRUE ON EVERY HOST, image included. The positive
control then names the directory where the runner really is, resolved from the
NON-isolated interpreter, so it is equally host-independent.

Substituting the interpreter is only half the substitution: `PYTHONPATH` routes
the runner into ANY interpreter, and the pinned image's own entrypoint exports
one naming the directory the runner is installed in. So the interpreter-path
variables are removed from the environment the shim runs under, and the shim is
then PROVEN runner-less under that exact environment before either direction is
measured (`_RUNNER_PATH_ENV`, `_shim_env`).

Both directions are asserted. A refusal test that cannot pass against the
repaired tree, and a recording test that cannot fail against the broken one, are
each half a control.

The gate's own wiring is EXECUTED, not grepped: the preflight block is pulled
out of `gatekeeper-land.sh` and run, so a block that was reduced to a comment,
made non-fatal, or moved behind the first arm is caught here. A text match
proves the script mentions the program; it does not prove the landing stops.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


#: Inner bounds for every subprocess this file launches, in seconds.
#:
#: `ci_harness_timeout_ceiling_check` publishes a per-call ceiling (the harness
#: bound divided by `CEILING_DIVISOR`) and reports any bound above it. This file
#: landed carrying 600 s and 120 s literals, and MEASURED at 49d2b3328 the
#: consequence was not local: the checker reported 6 findings across
#: `tools/ci/test_*.py`, `ci_harness_timeout_ceiling_check`'s own
#: `test_the_two_trees_use_different_globs_for_a_measured_reason` went red, and
#: because that file is in `ci_targeted_test_select`'s smoke floor — selected on
#: EVERY landing regardless of what changed — the `targeted tests` lane refused
#: every candidate. One bound in a test file made the repository unlandable.
#:
#: The values come from measured cost, not from the ceiling. In the pinned image:
#:     python3 -m venv --without-pip <dir>      0.06 s
#:     python3 -c "import pytest"               0.35 s
#:     the whole shell block under test         0.64 s   (slowest call in the file)
#:     both files, every test, end to end       1.30 s
#: so `_HEAVY` keeps roughly a hundredfold margin over the slowest call here and
#: `_QUICK` roughly eightyfold over the quickest. Neither is so low that a
#: healthy call cannot finish; both are low enough to still FIRE on a hang, which
#: `test_an_inner_bound_is_a_real_bound` proves rather than assumes.
_HEAVY = 60
_QUICK = 30

_ROOT = Path(__file__).resolve().parents[2]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_PROGRAMS = _ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
_PREFLIGHT_CALL = 'python3 "$PROGRAMS/landing_pytest_runtime_preflight.py"'
_HOST_LANE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"


def _land_lines() -> list[str]:
    return _LAND.read_text(encoding="utf-8").splitlines()


def _preflight_block() -> tuple[int, str]:
    """The shipped preflight guard, as executable shell, with its line number.

    Extracted rather than restated: a copy of the block in this file would pass
    forever after the real one was deleted, which is the shape of guard this
    repo has removed before.
    """
    lines = _land_lines()
    starts = [i for i, line in enumerate(lines)
              if line.startswith("if ! ") and _PREFLIGHT_CALL in line]
    assert len(starts) == 1, (
        "gatekeeper-land.sh does not guard the full tier with exactly one "
        f"fatal runtime preflight (found {len(starts)}). The landing arms "
        "cannot report on a host whose isolated interpreter has no test "
        "runner, so a landing without this guard emits NORECORD for every "
        "file in all three arms instead of one attributable refusal.")
    start = starts[0]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "fi")
    return start + 1, "\n".join(lines[start:end + 1])


def _first_arm_line() -> int:
    lines = _land_lines()
    return next(i + 1 for i, line in enumerate(lines)
                if line in {"  run_pytest", "run_pytest"})


#: Interpreter-path variables that route a SECOND copy of the runner into any
#: interpreter, substituted one included. `PYTHONPATH` prepends directories to
#: `sys.path` before site processing, so a venv with no runner installed still
#: imports one when the ambient value names the directory the runner lives in —
#: and that is not hypothetical. MEASURED inside the digest-pinned image, entered
#: the way this gate's own refusal text tells an operator to enter it
#: (`docker run … bash tools/gatekeeper-land.sh`), where the image entrypoint
#: exports::
#:
#:     PYTHONPATH=/headless/.local/lib/python3.12/site-packages:…:
#:                /usr/local/lib/python3.12/dist-packages:…
#:
#: and `/usr/local/lib/python3.12/dist-packages` is exactly where the runner is.
#: `landing_pytest_runtime_preflight.entry_probe` strips the same two names for
#: the same reason; this file has to strip them too or its substitution is not a
#: substitution. Under `docker exec`, which does not run the entrypoint, the
#: value is harmless — which is why the hole stayed invisible.
_RUNNER_PATH_ENV = ("PYTHONPATH", "PYTHONHOME")


def _shim_env(*, lane: str | None) -> dict[str, str]:
    """The exact environment the substituted interpreter will run under.

    Built once and used for BOTH the runner-less assertion below and the block
    run, because an interpreter proven runner-less under one environment says
    nothing about the environment the block actually executes in.
    """
    env = {key: value for key, value in os.environ.items()
           # See the same strip in the program: a nested entry that inherits its
           # supervisor's progress stream writes the parent's nonce from another
           # pid, and the parent's session is failed `schema/nonce/pid mismatch`
           # — this file's own result became UNKNOWN that way on the repo-tools
           # arm while every test in it passed.
           if not key.startswith("VIBEIC_PYTEST_PROGRESS")
           and key not in _RUNNER_PATH_ENV}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop(_HOST_LANE_ENV, None)
    if lane is not None:
        env[_HOST_LANE_ENV] = lane
    return env


def _runnerless_python(tmp_path: Path, env: dict[str, str]) -> Path:
    """An interpreter that genuinely cannot import the test runner, anywhere.

    A shell wrapper is not enough here. The block under test invokes bare
    `python3`, and the program it starts probes `sys.executable` — which a
    wrapper's `exec` replaces with the REAL interpreter, so the probe would
    measure the host and this test would invert inside the pinned image. A venv
    IS `sys.executable`: no system site directory, user site disabled, and no
    runner installed. That is true on every host, image included — PROVIDED the
    interpreter-path variables above are out of `env`, which is the caller's job
    and is asserted here rather than assumed.
    """
    home = tmp_path / "runnerless"
    made = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(home)], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=_HEAVY, check=False)
    if made.returncode != 0:
        pytest.skip("this interpreter cannot create a venv, so the "
                    "runner-less interpreter this test needs is UNAVAILABLE "
                    f"here — not verified: {made.stderr.strip()[:200]}")
    shim = home / "bin" / "python3"
    assert shim.is_file(), made.stdout + made.stderr
    probe = subprocess.run([str(shim), "-c", "import pytest"], env=env,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=_QUICK, check=False)
    assert probe.returncode != 0, (
        "the runner-less interpreter can still import the runner under the "
        "environment the block will run in, so the refusal direction of this "
        f"test would measure nothing: {probe.stdout}{probe.stderr}")
    return shim


def _real_site_dir() -> Path:
    """Where the runner actually lives, per the NON-isolated interpreter.

    Resolved rather than assumed so the positive control is the same test on a
    host (user site directory) and in the pinned image (system site directory).
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import pytest, sys; sys.stdout.write(pytest.__file__)"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=_QUICK, check=False)
    assert proc.returncode == 0, "this session has no importable test runner"
    return Path(proc.stdout.strip()).resolve().parents[1]


def _run_block(block: str, tmp_path: Path, *, lane: str | None) -> subprocess.CompletedProcess:
    script = tmp_path / "block.sh"
    script.write_text(
        "set -uo pipefail\n"
        f'PROGRAMS="{_PROGRAMS}"\n'
        + block + "\n"
        'echo "REACHED_THE_FIRST_ARM"\n',
        encoding="utf-8")
    env = _shim_env(lane=lane)
    shim = _runnerless_python(tmp_path, env)
    env["PATH"] = f"{shim.parent}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(["bash", str(script)], env=env, cwd=str(tmp_path),
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=_HEAVY, check=False)


def test_the_full_tier_refuses_once_when_it_cannot_run_the_test_runtime(tmp_path):
    """The refusal direction: no host lane, no importable runner under -I."""
    _, block = _preflight_block()
    proc = _run_block(block, tmp_path, lane=None)
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 2, combined
    assert "REACHED_THE_FIRST_ARM" not in combined, (
        "the preflight is not fatal — the landing continued into the arms, "
        "which is the every-file-NORECORD run this guard exists to prevent")
    # The CAUSE, named. A refusal a reader cannot attribute is the defect.
    assert "REFUSE" in combined
    assert "CAUSE" in combined
    # A runner-less interpreter takes the program's second cause branch; the
    # fleet's own user-site-suppression branch is asserted verbatim by
    # `programs/tests/test_landing_pytest_runtime_preflight.py`, which can model
    # that shape exactly. What is asserted HERE is what the shell must do about
    # any of them.
    assert "cannot import the test runner" in combined
    assert "trusted_pytest_entry.py" in combined
    # BOTH remedies, because a refusal with no way forward is a wall.
    assert "ghcr.io/vibeic/vibeic-eda@sha256:" in combined, (
        "the refusal does not name the digest-pinned runner image")
    assert f"{_HOST_LANE_ENV}=auto" in combined, (
        "the refusal does not name the host lane")
    # ONCE. Not once per file, not once per arm — which is the whole finding.
    verdicts = [line for line in combined.splitlines()
                if line.strip().startswith("REFUSE ")]
    assert len(verdicts) == 1, verdicts
    # The driver's per-file verdicts start the line; the refusal's prose only
    # explains what they would have been. Anchoring the check to the line start
    # is what tells one from the other.
    per_file = [line for line in combined.splitlines()
                if line.startswith(("NORECORD", "NOTRUN", "AGGREGATE_NORECORD"))]
    assert per_file == [], (
        "the gate emitted per-file UNKNOWNs instead of one attributable "
        f"refusal about the runtime: {per_file[:5]}")


def test_the_host_lane_lets_the_same_tree_record(tmp_path):
    """The recording direction, on the identical interpreter and tree.

    This is the half that FAILS on the reverted tree: without the host lane the
    entry cannot import the runner and the same block refuses.
    """
    _, block = _preflight_block()
    proc = _run_block(block, tmp_path, lane=str(_real_site_dir()))
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "REACHED_THE_FIRST_ARM" in combined, combined
    assert "host lane" in combined, combined


def test_the_preflight_is_asked_before_the_first_arm():
    """Order is the point: after the first arm it is a post-mortem, not a gate."""
    preflight_line, _ = _preflight_block()
    assert preflight_line < _first_arm_line(), (
        f"the runtime preflight is at line {preflight_line} but the first test "
        f"arm is invoked at {_first_arm_line()} — a gate that cannot look must "
        "say so before it spends the tier, not after")


def test_the_preflight_is_inside_the_full_tier_not_the_cheap_one():
    """`--cheap-only` runs no arm, so refusing it would refuse work that works."""
    lines = _land_lines()
    preflight_line, _ = _preflight_block()
    cheap_exit = next(i + 1 for i, line in enumerate(lines)
                      if line.startswith('if [ "$CHEAP_ONLY" = "1" ]'))
    assert preflight_line > cheap_exit, (
        "the preflight would refuse a --cheap-only run, which never spawns a "
        "test child and therefore never needed the runtime")


def test_the_preflight_program_owns_the_cause_and_the_remedy():
    """One owner for the text, so the script and the program cannot disagree."""
    program = _PROGRAMS / "landing_pytest_runtime_preflight.py"
    assert program.is_file(), f"{program} is absent"
    _, block = _preflight_block()
    for token in ("ghcr.io/vibeic/vibeic-eda@sha256:", _HOST_LANE_ENV,
                  "isolated mode"):
        assert token not in block, (
            f"gatekeeper-land.sh restates {token!r} instead of delegating the "
            "refusal text to the program that measures it")


def test_an_inner_bound_is_a_real_bound():
    """A bound above the ceiling is a defect; one that never binds is another.

    Three claims, because lowering a number can fail in three directions.

    TOO HIGH: both bounds must sit at or under the ceiling
    `ci_harness_timeout_ceiling_check` publishes for this tree, read from the
    program rather than restated here — a constant copied into a test rots the
    moment the harness bound moves.

    TOO LOW: the slowest call this file makes is measured HERE, in this session,
    and must finish inside a fraction of the smaller bound. A bound chosen from
    the ceiling instead of from the work is how a green suite becomes an
    intermittently red one on a loaded host.

    INERT: the bound must actually stop a child that does not return. Proved on
    the same `subprocess.run(..., timeout=...)` shape every call above uses, with
    a deliberately tiny bound so the proof itself is cheap — the shape and the
    raised `TimeoutExpired` are what is being pinned, not the number.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import ci_harness_timeout_ceiling_check as C

    ceiling = C.inner_timeout_ceiling(_ROOT)
    assert ceiling is not None, "this tree publishes no harness bound to divide"
    assert _HEAVY <= ceiling and _QUICK <= ceiling, (
        f"_HEAVY={_HEAVY} _QUICK={_QUICK} against a published ceiling of "
        f"{ceiling}: the gate that made this repository unlandable is exactly "
        "this comparison")

    start = time.monotonic()
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=_QUICK, check=False)
    elapsed = time.monotonic() - start
    assert probe.returncode == 0, probe.stderr
    assert elapsed < _QUICK / 4, (
        f"the quickest call this file makes took {elapsed:.2f}s against a "
        f"{_QUICK}s bound — the bound is no longer generous and will flake")

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-c", f"import time; time.sleep({_QUICK * 2})"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=1, check=False)
