"""The landing pytest runtime cannot be shadowed by the subject checkout."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
ENTRY = PROGRAMS / "trusted_pytest_entry.py"
IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
         "66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff")

#: THE STREAM THIS FILE'S CHILDREN MUST NOT JOIN.
#:
#: Every test here spawns the trusted entry, and the entry writes semantic
#: lifecycle events to the stream named by these variables. When this file is
#: itself run under `pytest_per_file_junit`, inheriting them makes each child
#: write the PARENT's nonce from a different pid, and the driver fails the
#: parent's whole session with `schema/nonce/pid mismatch` — the file's result
#: becomes UNKNOWN even though every test in it passed. MEASURED on the
#: repo-tools arm against a sibling file with the same shape.
_PROGRESS_ENV_PREFIX = "VIBEIC_PYTEST_PROGRESS"


def test_isolated_entry_ignores_subject_pytest_and_progress_plugin(tmp_path):
    isolated_probe = subprocess.run(
        [sys.executable, "-I", "-c", "import pytest"],
        capture_output=True, text=True)
    if isolated_probe.returncode != 0:
        import pytest
        pytest.skip("host isolated interpreter has no image-owned pytest")
    (tmp_path / "pytest.py").write_text(
        "raise AssertionError('subject pytest shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "_pytest_progress_plugin.py").write_text(
        "raise AssertionError('subject progress shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}
           and not key.startswith(_PROGRESS_ENV_PREFIX)}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    proc = subprocess.run(
        [sys.executable, "-I", str(ENTRY), "-q", "-p",
         "no:cacheprovider", "test_ok.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_nonisolated_entry_refuses_before_subject_collection(tmp_path):
    (tmp_path / "test_never.py").write_text(
        "raise AssertionError('subject collected')\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "-q", "test_never.py"],
        cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "requires python3 -I" in proc.stderr


def test_pinned_hermetic_image_ignores_subject_module_shadows(tmp_path):
    import pytest
    # A MISSING `docker` MUST SKIP, NOT RAISE. Without this the file cannot run
    # INSIDE the pinned image — which is the environment this very module names
    # as the remedy when the host cannot run the protected runtime, and the one
    # place the other tests here most need to be exercised. Measured in the
    # pinned image: `FileNotFoundError: [Errno 2] ... 'docker'`, a red that says
    # nothing about the subject.
    try:
        available = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except (FileNotFoundError, OSError) as exc:
        pytest.skip(f"no container engine is reachable here ({exc}) — the "
                    "hermetic image claim is UNVERIFIED, not verified")
    if available.returncode != 0:
        pytest.skip("exact hermetic landing image is not locally available")
    (tmp_path / "pytest.py").write_text(
        "raise AssertionError('subject pytest shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "_pytest_progress_plugin.py").write_text(
        "raise AssertionError('subject progress shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    tmp_path.chmod(0o755)
    for path in tmp_path.iterdir():
        path.chmod(0o644)
    repo = PROGRAMS.parents[3]
    proc = subprocess.run([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534", "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=1073741824",
        "--entrypoint", "python3",
        "-v", f"{repo}:/runtime:ro", "-v", f"{tmp_path}:/subject:ro",
        "-w", "/subject", IMAGE, "-I",
        "/runtime/vibe-ic-marketplace/plugins/vibe-ic/programs/"
        "trusted_pytest_entry.py",
        "-q", "-p", "no:cacheprovider", "test_ok.py",
    ], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


# ── THE HOST LANE ──────────────────────────────────────────────────────────
# `-I` implies `-s`, so the USER site directory is suppressed. That is the
# property this entry exists for on a pinned-image host and it is fatal on a
# host whose runner lives only there: `import pytest` raises, the entry refuses,
# and the child dies before one lifecycle event. MEASURED on the landing host at
# 7c376e348, the repo-tools arm alone: asked 40, recorded 0, NORECORD 40,
# aggregate INCOMPLETE, zero junit cases. Landing was impossible on any host.
#
# The interpreter is SUPPLIED to every test below, for the reason the sibling
# `tools/ci/test_landing_runtime_preflight_gate.py` states at length: the
# condition under test is a property of the host, so a test that uses the host's
# own interpreter measures the host and inverts inside the pinned image. `-S`
# keeps `sys.flags.isolated` and `sys.flags.ignore_environment` set — the
# entry's contract still holds — and removes every site directory, which makes
# "the isolated interpreter cannot import the runner" true on EVERY host.
_HOST_LANE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"
_AUTOLOAD_ENV = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"


def _siteless_python(tmp_path: Path) -> Path:
    shim = tmp_path / "shim" / "python3"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n',
                    encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _real_site_dir() -> Path:
    """Where the runner really is, per the NON-isolated interpreter."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import pytest, sys; sys.stdout.write(pytest.__file__)"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert proc.returncode == 0
    return Path(proc.stdout.strip()).resolve().parents[1]


def _isolated_site_dirs() -> list[Path]:
    """The directories an ISOLATED interpreter keeps on this installation.

    `-I` suppresses the USER site directory and nothing else, so these are what
    the fleet's real lane consumer still sees. Read from the interpreter rather
    than spelled out: the answer differs between a host and the pinned image and
    a literal would be right in only one of them.
    """
    proc = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys" + chr(10) + "for e in sys.path: print(e)"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # SITE DIRECTORIES ONLY. The stdlib directories on that path are already on
    # every interpreter's path, so naming them adds nothing the lane could
    # supply and makes the value harder to read. `site-packages` /
    # `dist-packages` is the naming both a host and the image use.
    return [Path(line) for line in proc.stdout.split()
            if line and Path(line).is_dir()
            and Path(line).name in {"site-packages", "dist-packages"}]


def _closure_lane() -> str:
    """A lane value naming the runner's WHOLE import closure, runner dir first.

    `_real_site_dir()` alone is HALF a closure on this fleet. MEASURED on 8HD-d
    at 46db018669::

        pytest, _pytest, pluggy, iniconfig, packaging
                                 -> ~/.local/lib/python3.12/site-packages
        pygments                 -> /usr/lib/python3/dist-packages

    `pytest` imports `pygments` lazily, at terminal-writer time, so the entry
    imports the runner and then dies mid-session with `No module named
    'pygments'` — and the `-S` shim below keeps NO site directory, so nothing
    else can supply it. Three tests in this file measured that host rather than
    this entry until the lane learned to take more than one directory.

    The runner's own directory stays FIRST, which is what the ordering and
    provenance assertions below are about.
    """
    seen: list[str] = []
    for source in [_real_site_dir(), *_isolated_site_dirs()]:
        item = str(source)
        if source.is_dir() and item not in seen:
            seen.append(item)
    return os.pathsep.join(seen)


def _subject(tmp_path: Path) -> Path:
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    return subject


def _entry(python: Path, subject: Path, **extra: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", _HOST_LANE_ENV}
           and not key.startswith(_PROGRESS_ENV_PREFIX)}
    env[_AUTOLOAD_ENV] = "1"
    env.update(extra)
    return subprocess.run(
        [str(python), "-I", str(ENTRY), "-q", "-p", "no:cacheprovider",
         "test_ok.py"],
        cwd=subject, env=env, capture_output=True, text=True)


def test_without_the_lane_a_siteless_isolated_entry_refuses(tmp_path):
    """The unrepaired shape, asserted so the repair has something to be a repair OF."""
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "[NORECORD] trusted pytest entry:" in proc.stderr
    assert "No module named 'pytest'" in proc.stderr


def test_the_named_lane_records_where_the_same_entry_refused(tmp_path):
    """THE REVERT GUARD. Remove the lane from `run()` and this goes red."""
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path),
                  **{_HOST_LANE_ENV: _closure_lane()})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_the_lane_is_inserted_at_the_front_not_appended(tmp_path):
    """MEASURED: appending mixes the lane's pure-Python against the system's C
    extensions and dies in the mismatch (cffi 2.0.0 vs _cffi_backend 1.15.0).
    Asserted on the resolved ORDER rather than on the crash, because the crash
    needs a host carrying that exact pair to reproduce.

    `insert(0, ...)` is what `run()` does, and the only thing that may sit ahead
    of the lane afterwards is pytest's own rootdir/basedir prepend at collection
    — shipped behaviour of prepend import mode, present on the pinned-image path
    too. Every OTHER entry must come after the lane, and the runner itself must
    have resolved FROM it, which is the claim that matters."""
    subject = _subject(tmp_path)
    lane = _real_site_dir()
    (subject / "test_ok.py").write_text(
        "import sys, pytest\n"
        "from pathlib import Path\n"
        f"LANE = {str(lane)!r}\n"
        "SUBJECT = str(Path(__file__).resolve().parent)\n"
        "def test_the_lane_answers_before_anything_it_was_inserted_ahead_of():\n"
        "    assert LANE in sys.path, sys.path\n"
        "    ahead = sys.path[:sys.path.index(LANE)]\n"
        "    assert all(item == SUBJECT for item in ahead), ahead\n"
        "def test_the_runner_resolved_from_the_lane():\n"
        "    assert pytest.__file__.startswith(LANE + '/'), pytest.__file__\n",
        encoding="utf-8")
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: _closure_lane()})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 passed" in proc.stdout, proc.stdout


def test_the_lane_refuses_without_the_autoload_pin(tmp_path):
    """The lane restores the directory's pytest11 entry points; on this fleet one
    of them takes the session down at collection. So the token is required by
    the entry rather than trusted to the caller."""
    subject = _subject(tmp_path)
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", _AUTOLOAD_ENV}
           and not key.startswith(_PROGRESS_ENV_PREFIX)}
    env[_HOST_LANE_ENV] = str(_real_site_dir())
    proc = subprocess.run(
        [str(_siteless_python(tmp_path)), "-I", str(ENTRY), "-q", "-p",
         "no:cacheprovider", "test_ok.py"],
        cwd=subject, env=env, capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert _AUTOLOAD_ENV in proc.stderr


def test_the_lane_cannot_be_the_subject_checkout(tmp_path):
    """The property the entry exists for. A runtime the subject can name is a
    runtime the subject controls, so the lane goes through the SAME
    `_under(resolved, subject)` refusal the module identities do."""
    subject = _subject(tmp_path)
    (subject / "fakesite").mkdir()
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: str(subject / "fakesite")})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "resolved inside the subject checkout" in proc.stderr


def test_the_lane_must_be_absolute_and_must_exist(tmp_path):
    subject = _subject(tmp_path)
    python = _siteless_python(tmp_path)
    relative = _entry(python, subject, **{_HOST_LANE_ENV: "fakesite"})
    assert relative.returncode == 2
    assert "must name an absolute directory" in relative.stderr
    missing = _entry(python, subject,
                     **{_HOST_LANE_ENV: str(tmp_path / "nowhere")})
    assert missing.returncode == 2
    assert "does not resolve" in missing.stderr


def test_the_identity_record_still_shows_which_lane_answered(tmp_path):
    """A host-lane session and a pinned-image session are different runtimes, so
    the receipt must show which one ran — and it must do so WITHOUT a new key.

    `pytest_per_file_junit._runtime_identity` validates the key set exactly.
    MEASURED when a `host_lane` field was added: `asked 41 recorded 0 NORECORD
    41`, every file "invalid trusted pytest runtime identity" — the repair
    reproducing the defect it repairs. The attested module rows already carry
    the resolved absolute path of every module the lane supplied, so the lane is
    a fact the existing record states.
    """
    subject = _subject(tmp_path)
    lane = _real_site_dir()
    (subject / "test_ok.py").write_text(
        "import json, os\n"
        f"LANE = {str(lane)!r}\n"
        "def test_the_record_keeps_its_exact_reviewed_key_set():\n"
        "    record = json.loads(os.environ['VIBEIC_PYTEST_RUNTIME_IDENTITY'])\n"
        "    assert set(record) == {'schema', 'python', 'entry', 'plugin',"
        " 'modules'}, sorted(record)\n"
        "def test_the_attested_modules_name_the_lane_that_supplied_them():\n"
        "    record = json.loads(os.environ['VIBEIC_PYTEST_RUNTIME_IDENTITY'])\n"
        "    rows = {row['name']: row['path'] for row in record['modules']}\n"
        "    assert set(rows) == {'pytest', '_pytest', 'pluggy'}, rows\n"
        "    assert all(path.startswith(LANE + '/') for path in rows.values()),"
        " rows\n",
        encoding="utf-8")
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: _closure_lane()})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 passed" in proc.stdout, proc.stdout


def test_a_half_closure_lane_is_not_silently_completed(tmp_path):
    """The refusal the widened value exists FOR, kept as a measurement.

    A lane naming the runner's own directory and nothing else is exactly what
    every caller wrote before, and on an installation whose closure is split it
    imports the runner and then cannot report. The entry must not paper over
    that by reaching for a directory nobody named — a silent fallback to the
    host's own site directories is the thing the module docstring refuses.

    On an installation whose closure IS one directory (the pinned image) there
    is nothing to be half of, so the session records and this test says so
    rather than asserting a refusal that cannot happen there.
    """
    runner_only = str(_real_site_dir())
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path),
                  **{_HOST_LANE_ENV: runner_only})
    if runner_only == _closure_lane():
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "[NORECORD] trusted pytest entry:" in proc.stderr
    # The cause is NAMED, so a reader is not left to infer which half is
    # missing. MEASURED on 8HD-d: "No module named 'pygments'".
    assert "No module named" in proc.stderr, proc.stderr


def test_every_named_directory_answers_in_the_order_it_was_named(tmp_path):
    """The widened value is a LIST, not a set and not one directory with noise.

    Asserted from inside the recorded session on `sys.path` itself, because the
    order is the whole contract: the first directory named must answer first,
    which is what keeps the runner resolving from the directory the provenance
    assertions above pin it to.
    """
    subject = _subject(tmp_path)
    value = _closure_lane()
    named = value.split(os.pathsep)
    (subject / "test_ok.py").write_text(
        "import sys\n"
        f"NAMED = {named!r}\n"
        "def test_each_named_directory_is_on_the_path_in_order():\n"
        "    where = [sys.path.index(item) if item in sys.path else -1\n"
        "             for item in NAMED]\n"
        "    assert -1 not in where, (where, NAMED, sys.path)\n"
        "    assert where == sorted(where), (where, NAMED, sys.path)\n",
        encoding="utf-8")
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: value})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout, proc.stdout


def test_an_empty_segment_in_the_lane_is_refused(tmp_path):
    """`a::b` is a caller mistake, and an empty segment would resolve to cwd."""
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path),
                  **{_HOST_LANE_ENV: _closure_lane() + os.pathsep + ""
                     + os.pathsep + str(_real_site_dir())})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "empty directory segment" in proc.stderr


def test_an_unset_lane_leaves_the_pinned_image_path_unchanged(tmp_path):
    """The default must be exactly the shipped behaviour: opting nobody in."""
    isolated_probe = subprocess.run(
        [sys.executable, "-I", "-c", "import pytest"],
        capture_output=True, text=True)
    if isolated_probe.returncode != 0:
        import pytest
        pytest.skip("host isolated interpreter has no image-owned pytest")
    subject = _subject(tmp_path)
    (subject / "test_ok.py").write_text(
        "import json, os\n"
        "def test_identity_keeps_its_reviewed_key_set():\n"
        "    record = json.loads(os.environ['VIBEIC_PYTEST_RUNTIME_IDENTITY'])\n"
        "    assert set(record) == {'schema', 'python', 'entry', 'plugin',"
        " 'modules'}, sorted(record)\n",
        encoding="utf-8")
    proc = _entry(Path(sys.executable), subject)
    assert proc.returncode == 0, proc.stdout + proc.stderr
