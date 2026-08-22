"""The landing gate must be able to RUN, or say once that it cannot.

vibe-ic v1.10.69 moved all three landing arms onto
`python3 -I "$PROGRAMS/trusted_pytest_entry.py"`.  `-I` implies `-s`, so the
USER site directory is off, and on an ordinary developer host that is the only
place `pip install pytest` puts the test runner.  Measured on the landing host
at 7c376e348:

    targeted     recorded 0   NORECORD  17
    repo tools   recorded 0   NORECORD  40
    unselectable recorded 0   NORECORD 110

Every child died at `import pytest` before emitting one lifecycle event.  That
is not a red suite and not a green one: it is 167 UNKNOWNs, which is the single
most expensive way for a gate to say "I could not look" and the exact shape
that let the regression land looking like a test failure.

So this file asserts two separable claims, and neither is a text match on a
reassuring word:

  A. On a host where the isolated runtime cannot import the runner, the gate
     REFUSES, once, naming the remedy — instead of measuring nothing 167 times.
     Driven by executing the shipped preflight function against a runtime that
     refuses, so the assertion is about behaviour, not about wording.

  B. A named host lane makes the runtime runnable, and it cannot be used to
     smuggle the subject checkout onto the isolated interpreter's path, in
     either containment direction, nor to re-expose the host's ambient
     entry-point plugins.

Reverting either half of the repair turns these red: without the preflight the
extraction in A finds no function, and without the lane the entry in B refuses
with `No module named` instead of running.
"""
from __future__ import annotations

import os
import site
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_PROGRAMS = _ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
_ENTRY = _PROGRAMS / "trusted_pytest_entry.py"
_PREFLIGHT = "preflight_trusted_runtime"
_LANE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"

#: The three top-level call sites the preflight has to precede. Written as the
#: exact source lines rather than as function names so that a preflight moved
#: below a lane — which would still "exist" — is caught.
_ARM_CALL_SITES = (
    "  run_pytest",
    "if run_repo_tools_pytest; then",
    "if run_unselectable_pytest; then",
)


def _extract_fn(name: str) -> str:
    """Pull `name() { ... }` out of the script, brace-matched at column 0."""
    src = _LAND.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(src) if line.startswith(f"{name}() {{")]
    assert len(starts) == 1, (
        f"{name} is not defined exactly once in gatekeeper-land.sh — the "
        "landing gate has no host-runtime preflight, so a host that cannot "
        "run the runtime is answered with NORECORD for every selected file "
        "instead of one attributable refusal")
    start = starts[0]
    end = next(i for i in range(start + 1, len(src)) if src[i] == "}")
    return "\n".join(src[start:end + 1])


def _child_env(**overrides: str | None) -> dict:
    """A child environment with the landing lane variables under our control.

    The gate exports the lane before it runs the arms, so a test that inherits
    the ambient environment would silently measure the gate's decision instead
    of its own case.
    """
    env = dict(os.environ)
    env.pop(_LANE_ENV, None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _user_site() -> Path | None:
    """This host's user site directory, if it exists and carries the runner."""
    probe = subprocess.run(
        [sys.executable, "-c",
         "import site; print(site.getusersitepackages())"],
        capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return None
    candidate = Path(probe.stdout.strip())
    if not candidate.is_dir():
        return None
    return candidate


# ── A. THE GATE REFUSES INSTEAD OF MEASURING NOTHING ────────────────────────


def test_the_preflight_refuses_a_runtime_that_cannot_import_the_runner(
        tmp_path):
    """Behavioural. The shipped preflight, run against a refusing runtime.

    The stub stands in for "this host's isolated interpreter has no runner",
    which is what the landing host actually is, and makes the case reproducible
    on a host where the runner IS importable in isolation.
    """
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "trusted_pytest_entry.py").write_text(textwrap.dedent("""\
        import sys
        print("[NORECORD] trusted pytest entry: "
              "No module named 'pytest'", file=sys.stderr)
        raise SystemExit(2)
        """), encoding="utf-8")
    root = tmp_path / "subject"
    root.mkdir()

    script = (
        "set -uo pipefail\n"
        f'ROOT="{root}"\n'
        f'PROGRAMS="{programs}"\n'
        + _extract_fn(_PREFLIGHT) + "\n"
        + _PREFLIGHT + "\n"
        'echo "PREFLIGHT_RC=$?"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, env=_child_env(), timeout=300)
    out = proc.stdout + proc.stderr

    assert "PREFLIGHT_RC=1" in out, out
    assert "REFUSE" in out, out
    # The remedy, named. A refusal a reader cannot act on costs the same hour.
    assert "digest-pinned runner image" in out, out
    assert _LANE_ENV in out, out
    # The runtime's OWN words are relayed, so the refusal is attributable to a
    # cause rather than to the gate's opinion of the host.
    assert "[NORECORD] trusted pytest entry:" in out, out


def test_the_preflight_accepts_a_runtime_that_can_import_the_runner(tmp_path):
    """The paired negative: the refusal above is a decision, not a constant.

    Without this, a preflight hard-wired to refuse would pass the test above
    and block every landing on every host.
    """
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "trusted_pytest_entry.py").write_text(
        'print("[RUNTIME] trusted pytest entry: runner admitted")\n',
        encoding="utf-8")
    root = tmp_path / "subject"
    root.mkdir()

    script = (
        "set -uo pipefail\n"
        f'ROOT="{root}"\n'
        f'PROGRAMS="{programs}"\n'
        + _extract_fn(_PREFLIGHT) + "\n"
        + _PREFLIGHT + "\n"
        'echo "PREFLIGHT_RC=$?"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, env=_child_env(), timeout=300)
    out = proc.stdout + proc.stderr

    assert "PREFLIGHT_RC=0" in out, out
    assert "REFUSE" not in out, out


def test_the_preflight_runs_before_any_arm_and_its_refusal_stops_the_gate():
    """Structural. A preflight that runs after an arm has already answered
    UNKNOWN 167 times has bought nothing.
    """
    lines = _LAND.read_text(encoding="utf-8").splitlines()
    call = [i for i, line in enumerate(lines)
            if line == f"if ! {_PREFLIGHT}; then"]
    assert len(call) == 1, (
        f"{_PREFLIGHT} is not invoked exactly once at a top-level refusal site")
    site_line = call[0]

    for arm in _ARM_CALL_SITES:
        arm_lines = [i for i, line in enumerate(lines) if line == arm]
        assert arm_lines, f"the arm call site {arm!r} is gone"
        assert site_line < min(arm_lines), (
            f"{_PREFLIGHT} runs after {arm!r}; a gate that cannot look must "
            "say so before it spends an arm saying nothing")

    # The refusal must LEAVE. Setting a flag would let the arms run anyway and
    # bury one refusal under 167 NORECORDs.
    body = "\n".join(lines[site_line:site_line + 4])
    assert "exit 2" in body, body

    # The probe must be the same executable the arms launch, or it measures a
    # different runtime than the one that will run the tests.
    joined = "\n".join(lines[site_line - 60:site_line])
    assert 'python3 -I "$PROGRAMS/trusted_pytest_entry.py"' in joined, joined


# ── B. THE HOST LANE, AND WHAT IT MUST STILL REFUSE ─────────────────────────


def _needs_user_site() -> Path:
    lane = _user_site()
    if lane is None:
        pytest.skip(
            "this host has no user site directory, so the host lane cannot be "
            "exercised here — UNVERIFIED, which is not the same as verified")
    return lane


def test_a_named_host_lane_makes_the_isolated_runtime_run_tests(tmp_path):
    """The claim the whole repair exists for, asserted by running a test."""
    lane = _needs_user_site()
    if not (lane / "pytest").is_dir() and not (lane / "pytest.py").is_file():
        pytest.skip(
            f"the runner is not installed in {lane} — the lane has nothing to "
            "admit here, which is UNVERIFIED rather than verified")
    (tmp_path / "test_probe.py").write_text(
        "def test_probe():\n    assert True\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-I", str(_ENTRY), "-q", "-p", "no:cacheprovider",
         "test_probe.py"],
        cwd=tmp_path, env=_child_env(**{_LANE_ENV: str(lane)}),
        capture_output=True, text=True, timeout=600)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout, proc.stdout + proc.stderr


def test_the_runtime_probe_reports_which_lane_admitted_the_runner(tmp_path):
    """`--check-runtime` is what the preflight asks; it must answer honestly."""
    lane = _needs_user_site()
    proc = subprocess.run(
        [sys.executable, "-I", str(_ENTRY), "--check-runtime"],
        cwd=tmp_path, env=_child_env(**{_LANE_ENV: str(lane)}),
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        pytest.skip(
            "neither the image nor this host's user site can supply the "
            f"runner: {proc.stderr.strip()}")
    assert "[RUNTIME]" in proc.stdout, proc.stdout
    assert str(lane) in proc.stdout, proc.stdout


def test_a_lane_inside_the_subject_checkout_is_refused(tmp_path):
    """The property `-I` was chosen for survives the lane.

    A lane the subject can write is a lane the subject can shadow the runner
    with, which is precisely what isolation is for.
    """
    (tmp_path / "test_never.py").write_text(
        "raise AssertionError('subject collected')\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", str(_ENTRY), "-q", "-p", "no:cacheprovider",
         "test_never.py"],
        cwd=tmp_path, env=_child_env(**{_LANE_ENV: str(tmp_path)}),
        capture_output=True, text=True, timeout=600)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "shares a tree with the subject checkout" in proc.stderr, proc.stderr
    assert "subject collected" not in proc.stdout + proc.stderr


def test_a_lane_that_contains_the_subject_checkout_is_refused(tmp_path):
    """The other containment direction. A lane ABOVE the checkout would put
    the subject's own modules on the isolated path just as effectively.
    """
    subject = tmp_path / "checkout"
    subject.mkdir()
    (subject / "test_never.py").write_text(
        "raise AssertionError('subject collected')\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", str(_ENTRY), "-q", "-p", "no:cacheprovider",
         "test_never.py"],
        cwd=subject, env=_child_env(**{_LANE_ENV: str(tmp_path)}),
        capture_output=True, text=True, timeout=600)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "shares a tree with the subject checkout" in proc.stderr, proc.stderr


def test_the_lane_refuses_unless_ambient_plugin_autoload_is_off(tmp_path):
    """Restoring the user site restores its entry points with it.

    Measured on the landing host and documented at `gatekeeper-land.sh`: of the
    installed entry points exactly one raises at import and takes the session
    down AT COLLECTION, so nothing runs. Autoload being off is a PRECONDITION
    of the lane, and an unmet precondition must be named here rather than
    surface as an unattributable collection error.
    """
    lane = _needs_user_site()
    (tmp_path / "test_probe.py").write_text(
        "def test_probe():\n    assert True\n", encoding="utf-8")
    env = _child_env(**{_LANE_ENV: str(lane)})
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)

    proc = subprocess.run(
        [sys.executable, "-I", str(_ENTRY), "-q", "-p", "no:cacheprovider",
         "test_probe.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in proc.stderr, proc.stderr


def test_the_lane_is_off_unless_it_is_named(tmp_path):
    """No lane is derived behind the operator's back inside the entry.

    The derivation lives in the gate, in the open, where its refusal branch is
    reviewable. An entry that silently adopted the ambient user site would make
    the isolated shape a fiction on every host.
    """
    assert "getusersitepackages" not in _ENTRY.read_text(encoding="utf-8"), (
        "the entry derives a site directory for itself; the lane must be "
        "named by the operator or by the gate, never inferred silently")
    del tmp_path
