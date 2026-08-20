"""`landing_pytest_runtime_preflight.py` must refuse ONCE and say why.

The behavioural half of this guard — that `gatekeeper-land.sh` actually stops
when the program refuses, and stops BEFORE the first arm — lives in
`tools/ci/test_landing_runtime_preflight_gate.py`, which is inside the arm it
guards. This file owns the program's own contract: which lane it reports, what
its refusal must name, and that it never turns "I could not look" into a pass.

Every test supplies its interpreter. The condition under test is a property of
the host, so using the host's own interpreter would measure the host and invert
inside the pinned image; `<real python3> -S` keeps `sys.flags.isolated` and
`sys.flags.ignore_environment` set while removing every site directory, which
makes the refusal direction true on EVERY host.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
PROGRAM = PROGRAMS / "landing_pytest_runtime_preflight.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "_vibeic_landing_runtime_preflight_under_test", PROGRAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def program():
    return _module()


def _fleet_shaped_python(tmp_path: Path) -> str:
    """An interpreter with THIS FLEET's exact shape, on any host.

    Isolated mode has no site directory; ordinary mode has the host's. That is
    what all seven hosts really look like and what the pinned image does not, so
    modelling it — rather than borrowing whichever shape the host happens to
    have — is what makes both directions of this file assert something.

    `-S` is added only when `-I` is present, so the program's non-isolated
    fallback probe still resolves the runner and the refusal can name WHERE it
    is. A shim that always added `-S` would report "not installed anywhere",
    which is a different cause with a different remedy.
    """
    shim = tmp_path / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        'for arg in "$@"; do\n'
        '  if [ "$arg" = "-I" ]; then exec "%s" -S "$@"; fi\n'
        "done\n"
        'exec "%s" "$@"\n' % (sys.executable, sys.executable),
        encoding="utf-8")
    shim.chmod(0o755)
    return str(shim)


def _runnerless_python(tmp_path: Path) -> Path:
    """An interpreter that IS `sys.executable` and cannot import the runner.

    The two CLI tests below start the program as a subprocess, and the program
    probes `sys.executable`. A shell wrapper's `exec` replaces argv[0] with the
    real interpreter, so those tests would measure the host and would pass on
    this fleet while inverting inside the pinned image — MEASURED: rc 0 with
    `"reason": "... via the image lane"`. A venv is genuinely `sys.executable`:
    no system site directory, user site disabled, no runner installed.
    """
    home = tmp_path / "runnerless"
    made = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(home)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    if made.returncode != 0:
        pytest.skip("this interpreter cannot create a venv, so the runner-less "
                    "interpreter this test needs is UNAVAILABLE here — not "
                    f"verified: {made.stderr.strip()[:200]}")
    shim = home / "bin" / "python3"
    assert shim.is_file(), made.stdout + made.stderr
    return shim


def _real_site_dir() -> Path:
    proc = subprocess.run(
        [sys.executable, "-c",
         "import pytest, sys; sys.stdout.write(pytest.__file__)"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert proc.returncode == 0
    return Path(proc.stdout.strip()).resolve().parents[1]


def test_it_refuses_when_the_isolated_runtime_cannot_import_and_no_lane_is_set(
        program, tmp_path, monkeypatch):
    monkeypatch.delenv(program.HOST_LANE_ENV, raising=False)
    result = program.preflight(programs=PROGRAMS,
                               python=_fleet_shaped_python(tmp_path))
    assert result["ok"] is False
    assert result["isolated_import"] is False
    assert result["lane"] is None
    text = "\n".join(result["lines"])
    # The CAUSE, not a symptom. A refusal a reader cannot attribute is the
    # defect this program exists for.
    assert "isolated mode" in text
    assert "USER" in text and "site directory" in text
    # BOTH remedies, because a refusal with no way forward is a wall.
    assert program.RUNNER_IMAGE in text
    assert f"{program.HOST_LANE_ENV}={program.HOST_LANE_AUTO}" in text
    # WHERE the runner really is. "It is installed, just not where -I looks" is
    # the whole diagnosis; a reader must not need a second command for it.
    assert "site-packages" in text or "dist-packages" in text


def test_the_named_lane_makes_the_same_interpreter_report(program, tmp_path,
                                                          monkeypatch):
    """THE REVERT GUARD for the host lane, at the program's own boundary."""
    monkeypatch.setenv(program.HOST_LANE_ENV, str(_real_site_dir()))
    result = program.preflight(programs=PROGRAMS,
                               python=_fleet_shaped_python(tmp_path))
    assert result["ok"] is True, result["reason"]
    assert result["probe_returncode"] == 0
    assert "host lane" in "\n".join(result["lines"])


def test_it_executes_the_real_entry_rather_than_only_importing(program,
                                                               tmp_path,
                                                               monkeypatch):
    """A runtime that imports and cannot report produces the identical
    every-file-UNKNOWN shape, so the import alone is not the question.

    Driven by pointing the program at a directory whose `trusted_pytest_entry.py`
    imports fine and then exits non-zero: an import-only check would call this
    host ready and spend the tier finding out otherwise.
    """
    monkeypatch.setenv(program.HOST_LANE_ENV, str(_real_site_dir()))
    fake = tmp_path / "programs"
    fake.mkdir()
    (fake / "trusted_pytest_entry.py").write_text(
        "import sys\nsys.stderr.write('[NORECORD] counterfeit entry\\n')\n"
        "raise SystemExit(2)\n", encoding="utf-8")
    result = program.preflight(programs=fake, python=sys.executable)
    assert result["ok"] is False
    assert result["probe_returncode"] == 2
    assert "could not execute and report" in result["reason"]
    assert "counterfeit entry" in "\n".join(result["lines"])


def test_a_missing_entry_is_a_refusal_and_never_a_pass(program, tmp_path):
    result = program.preflight(programs=tmp_path, python=sys.executable)
    assert result["ok"] is False
    assert "absent" in result["reason"]


def test_the_probe_pins_plugin_autoload_off_on_the_child(program, tmp_path):
    """`gatekeeper-land.sh:520-528`: one installed entry point on this fleet
    raises at import and takes the session down at collection, so the probe must
    measure the same environment the arms use — asserted, not assumed."""
    entry = tmp_path / "trusted_pytest_entry.py"
    entry.write_text(
        "import os, sys\n"
        "sys.stdout.write('1 passed\\n')\n"
        "raise SystemExit(0 if os.environ.get("
        "'PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1' else 3)\n",
        encoding="utf-8")
    proc = program.entry_probe(sys.executable, entry)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_cli_exit_code_is_two_for_refuse_and_zero_for_pass(tmp_path,
                                                               monkeypatch):
    env = dict(os.environ)
    env.pop("VIBEIC_TRUSTED_PYTEST_SITE", None)
    shim = _runnerless_python(tmp_path)

    refuse = subprocess.run([str(shim), str(PROGRAM), "--json"], env=env,
                            stdin=subprocess.DEVNULL, capture_output=True,
                            text=True)
    assert refuse.returncode == 2, refuse.stdout + refuse.stderr
    assert json.loads(refuse.stdout)["ok"] is False

    env["VIBEIC_TRUSTED_PYTEST_SITE"] = str(_real_site_dir())
    allow = subprocess.run([str(shim), str(PROGRAM), "--json"], env=env,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True)
    assert allow.returncode == 0, allow.stdout + allow.stderr
    payload = json.loads(allow.stdout)
    assert payload["ok"] is True
    assert payload["lane"] == env["VIBEIC_TRUSTED_PYTEST_SITE"]


def test_the_refusal_goes_to_stderr_and_the_pass_to_stdout(tmp_path):
    """A gate's refusal that arrives on stdout is a refusal a log filter loses."""
    shim = _runnerless_python(tmp_path)
    env = dict(os.environ)
    env.pop("VIBEIC_TRUSTED_PYTEST_SITE", None)
    refuse = subprocess.run([str(shim), str(PROGRAM)], env=env,
                            stdin=subprocess.DEVNULL, capture_output=True,
                            text=True)
    assert refuse.returncode == 2
    assert "REFUSE" in refuse.stderr
    assert refuse.stdout.strip() == ""


# ══════════════════════════════════════════════════════════════════════
# THE REMEDY MUST RUN AS PRINTED.
#
# The refusal used to print
#
#     docker run --rm -v "$PWD:$PWD" -w "$PWD" <image> bash tools/gatekeeper-land.sh
#
# and that command does not work. The image's ENTRYPOINT is the iic-osic-tools
# launcher, whose own usage says: "-s, --skip … WARNING: this must be the first
# parameter to the script or it is ignored!". MEASURED 2026-08-20 against the
# pinned digest:
#
#     … <image> bash -c 'echo HELLO'          -> [ERROR] Unexpected option "bash", rc 1
#     … <image> --skip bash -c 'echo HELLO'   -> HELLO, rc 0
#
# The reader hitting this refusal is already blocked; a remedy that fails is a
# second failure to debug and no way forward.
#
# THE TEST EXECUTES THE PRINTED COMMAND. A text assertion — "the line contains
# --skip" — would have passed for the entire life of the broken line if it had
# been written against the old text, and it can only ever pin the mistake
# somebody thought of. Running it pins the property.
# ══════════════════════════════════════════════════════════════════════

_MARKER = "vibeic-remedy-ran-as-printed"


def _docker_image_available(image: str) -> str:
    """"" if the image can be run here, else the sentence naming why not.

    A skip and a pass must never be the same verdict (`_published_corpus`'s rule,
    and `#1357`'s): if this host cannot reach the image the test says which of
    the two facts it observed, and never reports the remedy as verified.
    """
    try:
        d = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:      # noqa: BLE001
        return f"docker cannot be run on this host ({exc})"
    if d.returncode != 0:
        return ("docker is present but its daemon did not answer: "
                + (d.stderr or d.stdout).strip()[:200])
    p = subprocess.run(["docker", "image", "inspect", image],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return (f"the digest-pinned runner image is not present locally and this "
                f"test does not pull 31 GB: {image}")
    return ""


def test_the_printed_image_remedy_RUNS_as_printed(program, tmp_path):
    """Execute what the refusal prints. Not what it says — what it builds."""
    why = _docker_image_available(program.RUNNER_IMAGE)
    if why:
        pytest.skip("the image lane could not be exercised here — " + why
                    + ". THIS IS 'could not look', not 'the remedy works'.")
    argv = program.image_lane_argv(
        ("bash", "-c", f"echo {_MARKER}"), workdir=str(tmp_path))
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, (
        "the remedy the refusal prints did not run\n"
        + " ".join(argv) + f"\nrc={r.returncode}\n{r.stdout}\n{r.stderr}")
    assert _MARKER in r.stdout, (
        "the remedy exited 0 without running the command it was given\n"
        + r.stdout + r.stderr)


def test_the_remedy_would_FAIL_without_the_entrypoint_skip(program, tmp_path):
    """The negative control. Without it the test above proves only that `docker
    run` exists — it would pass against an image with no entrypoint at all."""
    why = _docker_image_available(program.RUNNER_IMAGE)
    if why:
        pytest.skip("the image lane could not be exercised here — " + why
                    + ". THIS IS 'could not look', not 'the control held'.")
    argv = program.image_lane_argv(
        ("bash", "-c", f"echo {_MARKER}"), workdir=str(tmp_path))
    argv.remove(program.IMAGE_ENTRYPOINT_SKIP)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    assert r.returncode != 0 and _MARKER not in r.stdout, (
        "dropping the entrypoint skip changed nothing, so the test above is not "
        "measuring the entrypoint\n" + r.stdout + r.stderr)


def test_the_printed_lines_are_the_argv_and_cannot_drift_from_it(program):
    """One source for the command. A second copy in the refusal text is how the
    two disagree, which is what happened."""
    printed = "\n".join(program._image_lane_lines())
    argv = program.image_lane_argv()
    flat = printed.replace("\\\n", " ").replace('"', "")
    for word in argv:
        assert word in flat, f"{word!r} is printed nowhere:\n{printed}"
    assert flat.split().index(program.IMAGE_ENTRYPOINT_SKIP) == \
        flat.split().index(program.RUNNER_IMAGE) + 1, (
        "the entrypoint skip is not the FIRST parameter after the image, which "
        "is the one placement the launcher accepts:\n" + printed)


def test_the_refusal_body_carries_the_runnable_remedy(program, tmp_path):
    """And it reaches the reader — the lines are built, but they must be emitted."""
    lines = program._refusal_lines(python="/nonexistent/python3", isolated_ok=False,
                                   resolved="", lane=None, probe=None)
    body = "\n".join(lines)
    assert f"{program.RUNNER_IMAGE} \\" in body, body
    assert program.IMAGE_ENTRYPOINT_SKIP + " bash tools/gatekeeper-land.sh" in body, body
