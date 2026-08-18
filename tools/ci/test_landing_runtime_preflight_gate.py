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
from pathlib import Path

import pytest


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


def _runnerless_python(tmp_path: Path) -> Path:
    """An interpreter that genuinely cannot import the test runner, anywhere.

    A shell wrapper is not enough here. The block under test invokes bare
    `python3`, and the program it starts probes `sys.executable` — which a
    wrapper's `exec` replaces with the REAL interpreter, so the probe would
    measure the host and this test would invert inside the pinned image. A venv
    IS `sys.executable`: no system site directory, user site disabled, and no
    runner installed. That is true on every host, image included.
    """
    home = tmp_path / "runnerless"
    made = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(home)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=600, check=False)
    if made.returncode != 0:
        pytest.skip("this interpreter cannot create a venv, so the "
                    "runner-less interpreter this test needs is UNAVAILABLE "
                    f"here — not verified: {made.stderr.strip()[:200]}")
    shim = home / "bin" / "python3"
    assert shim.is_file(), made.stdout + made.stderr
    probe = subprocess.run([str(shim), "-c", "import pytest"],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=120, check=False)
    assert probe.returncode != 0, (
        "the runner-less interpreter can still import the runner, so the "
        "refusal direction of this test would measure nothing")
    return shim


def _real_site_dir() -> Path:
    """Where the runner actually lives, per the NON-isolated interpreter.

    Resolved rather than assumed so the positive control is the same test on a
    host (user site directory) and in the pinned image (system site directory).
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import pytest, sys; sys.stdout.write(pytest.__file__)"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=120, check=False)
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
    shim = _runnerless_python(tmp_path)
    env = {key: value for key, value in os.environ.items()
           # See the same strip in the program: a nested entry that inherits its
           # supervisor's progress stream writes the parent's nonce from another
           # pid, and the parent's session is failed `schema/nonce/pid mismatch`
           # — this file's own result became UNKNOWN that way on the repo-tools
           # arm while every test in it passed.
           if not key.startswith("VIBEIC_PYTEST_PROGRESS")}
    env["PATH"] = f"{shim.parent}{os.pathsep}{env.get('PATH', '')}"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop(_HOST_LANE_ENV, None)
    if lane is not None:
        env[_HOST_LANE_ENV] = lane
    return subprocess.run(["bash", str(script)], env=env, cwd=str(tmp_path),
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=600, check=False)


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
