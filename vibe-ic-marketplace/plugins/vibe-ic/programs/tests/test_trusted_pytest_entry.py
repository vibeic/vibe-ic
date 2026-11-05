"""The landing pytest runtime cannot be shadowed by the subject checkout."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _tool_probes as NV  # noqa: E402
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated


PROGRAMS = Path(__file__).resolve().parents[1]
ENTRY = PROGRAMS / "trusted_pytest_entry.py"

#: THE REFERENCE IS COMPOSED, NOT COPIED (vibe-ic#2100).
#:
#: This was the literal `ghcr.io/vibeic/vibeic-eda@sha256:8c5694…`, which welds
#: the pinned DIGEST (identity) to a REPOSITORY (deployment configuration).  The
#: digest half is a second definition of the pin; the repository half is simply
#: wrong on any host that reaches the same bytes elsewhere.
#:
#: MEASURED 2026-09-07 on 8HD-4 with `VIBEIC_EDA_IMAGE_REPO` exported: the
#: pinned bytes were present under the configured repository and absent under
#: `ghcr.io`, so `docker image inspect` failed and
#: `test_image_entry_ignores_subject_shadow` reported
#: "exact hermetic landing image is not locally available" — a SKIP, in
#: pytest's green bucket, on every host that carries the fleet configuration.
#: The one test that proves the landing runtime cannot be shadowed inside the
#: image had quietly stopped running there, and nothing said so.
#:
#: `_eda_pin` is a different module from the subject (`trusted_pytest_entry`),
#: so reading it here is not circular; it is the same composition every other
#: run-path site performs.
#:
#: RESOLVED WHEN THE TEST RUNS, NOT AT COLLECTION (lane rfimg2). This was
#: `IMAGE = _pin.image_reference()` at module level, which asks THIS HOST's
#: docker: inside the image (no docker) the whole file was a collection error,
#: so the eleven tests here that need no image at all never ran either.
def _landing_image():
    """`(reference, why_not)` -- the reference this host holds for the pin."""
    try:
        return _pin.image_reference(), ""
    except _pin.ImageNotResolvable as exc:
        return None, str(exc)

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
        "import sys\n"
        "def test_ok():\n"
        "    legacy = sys.modules.get('_pytest_progress_plugin')\n"
        "    protected = sys.modules['_vibeic_protected_pytest_progress']\n"
        "    assert legacy is protected\n"
        "    assert legacy.domain_progress is protected.domain_progress\n",
        encoding="utf-8")
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
    if shutil.which("docker") is None:
        NV.skip_not_verified(
            "no container engine is reachable here (no `docker` on PATH), so "
            "the hermetic image claim could not be tested",
            remedy="install a container engine and pull the pinned vibeic-eda "
                   "image")
    IMAGE, why_not = _landing_image()
    if IMAGE is None:
        NV.skip_not_verified(
            f"the pinned landing image is not held on this host ({why_not}), "
            f"so the hermetic image claim could not be tested",
            remedy="pull the pinned vibeic-eda image onto this host")
    try:
        available = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except (FileNotFoundError, OSError) as exc:
        # THROUGH THE TIER, not past it. The sentence was already honest — "the
        # hermetic image claim is UNVERIFIED, not verified" — and an honest
        # sentence in a bare `pytest.skip` still lands in pytest's `skipped`
        # bucket, which is green, and reaches no roll-up. That is the whole of
        # vibe-ic#1128. `skip_not_verified` stamps the same fact where the
        # summary can read it, and carries the remedy with it.
        NV.skip_not_verified(
            f"no container engine is reachable here ({exc}), so the hermetic "
            f"image claim could not be tested",
            remedy=f"install a container engine and `docker pull {IMAGE}`")
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


def _site_processing_dirs() -> list[Path]:
    """Every directory SITE PROCESSING adds to this installation's path.

    Derived as a set difference -- what the ordinary interpreter can import
    from, MINUS what an interpreter with site processing off (`-S -I`) can --
    rather than by matching the names `site-packages` and `dist-packages`. The
    name match was the first shape and it is a guess about two spellings: it
    silently returns an INCOMPLETE lane on any installation that adds a
    directory under some other name, or one a `.pth` file injected.

    BOTH ARMS RUN WITHOUT `PYTHONPATH`/`PYTHONHOME`, and that is load-bearing
    rather than tidy. `-I` implies `-E`, so the siteless arm cannot honour them
    and the ordinary arm can -- an asymmetry that puts every ambient entry into
    the difference as though site processing had added it. MEASURED: under the
    landing arm, `pytest_per_file_junit` prepends the plugin's own `programs`
    directory to `PYTHONPATH` for every child it spawns, so the lane came out
    naming a directory INSIDE the checkout and `trusted_pytest_entry` refused
    it -- `VIBEIC_TRUSTED_PYTEST_SITE resolved inside the subject checkout`.
    The entry's guard was right; the lane this helper built was wrong.

    Anything inside the repository is dropped for that same reason. The entry
    OWNS that refusal and keeps it; this is a builder obeying the contract it
    builds for, not a second copy of the check. An editable install pointing at
    the checkout would otherwise reintroduce exactly the failure above on a host
    that happens to have one.

    The difference is also what makes the ordering assertion sound: none of
    these directories is on a siteless interpreter's path by construction, so
    when the lane names them they appear because the lane named them.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}

    def seen(*flags: str) -> list[str]:
        proc = subprocess.run(
            [sys.executable, *flags, "-c",
             "import sys" + chr(10) + "for e in sys.path: print(e)"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        return [line for line in proc.stdout.split()
                if line and Path(line).is_dir()]

    siteless = set(seen("-S", "-I"))
    out: list[Path] = []
    for item in seen():
        if item in siteless:
            continue
        resolved = Path(item).resolve()
        if resolved == PROGRAMS.parents[3] or PROGRAMS.parents[3] in resolved.parents:
            continue
        out.append(resolved)
    return out


def _shadowing_lane_segments(value: str) -> list[str]:
    """The segments of a lane VALUE whose top level shadows a stdlib module.

    Measured with the entry's own `_stdlib_shadows`, so the test and the
    subject cannot disagree about what a shadow is.
    """
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("_tpe_subject", ENTRY)
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = getattr(module, "_stdlib_shadows", None)
    if probe is None:          # pre-repair subject: it cannot answer, so the
        return []              # guard stands down and the arm goes red below
    named = []
    for segment in value.split(os.pathsep):
        segment = segment.strip()
        if not segment:
            continue
        lane = Path(segment)
        if lane.is_dir() and probe(lane.resolve()):
            hits = probe(lane.resolve())
            named.append(f"{lane}: " + ", ".join(n for n, _ in hits))
    return named


def _unshadowed_closure_lane(tmp_path: Path) -> str:
    """The runner's closure with every stdlib shadow REMOVED, as a lane value.

    WHY THIS EXISTS. The two direction-1 controls below assert that a clean
    lane is still ADMITTED -- without them the repair could be "refuse
    everything" and nobody would notice. On this host `_closure_lane()`
    contains the `argparse 1.4.0` shadow, so routing them through
    `_require_unshadowed_lane` made both SKIP: a control that does not run is
    not a control. MEASURED before this helper: `11 passed, 8 skipped`, with
    both direction-1 ids among the skips.

    Each shadowed segment is replaced by a symlink mirror of itself with the
    shadowing names left out, so the runner still resolves and the lane is
    clean on ANY host, shadowed or not.
    """
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("_tpe_subject_u", ENTRY)
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = getattr(module, "_stdlib_shadows", None)
    if probe is None:
        return _closure_lane()
    out: list[str] = []
    for index, segment in enumerate(_closure_lane().split(os.pathsep)):
        lane = Path(segment.strip())
        if not lane.is_dir():
            continue
        hits = probe(lane.resolve())
        if not hits:
            out.append(str(lane))
            continue
        drop = {path.name for _, path in hits}
        mirror = tmp_path / f"unshadowed{index}"
        mirror.mkdir(parents=True, exist_ok=True)
        for item in lane.iterdir():
            if item.name in drop:
                continue
            link = mirror / item.name
            if not link.exists():
                link.symlink_to(item)
        out.append(str(mirror))
    return os.pathsep.join(out)


def _require_unshadowed_lane(value: str) -> str:
    """SKIP, not fail, when THIS HOST's real site directory shadows the stdlib.

    These four tests hand the entry a REAL host lane in order to observe what
    the entry does with it -- front-insertion, ordering, the identity record.
    On a host whose site directory shadows a stdlib module the entry now
    REFUSES that lane by name (its third refusal), so the session under test
    never starts and the property is not observable here.

    Reporting that as a FAILURE says the tree is broken when what was measured
    is a condition of this machine's user site. MEASURED on 8HD-9: 303 stdlib
    names, one shadow, `argparse 1.4.0` in the user site, and these same four
    ids red on CLEAN main for it. The honest word is the one this module
    already uses for an environment it cannot supply: skip, with the shadow
    NAMED so the reader is sent to the right file.

    This does not weaken the assertions below -- they are unchanged and still
    run wherever the lane is clean. The host repair is `pip uninstall argparse`
    and it belongs to whoever owns the box, not to a lane.
    """
    import pytest  # this module imports pytest at use site, not at module level
    shadowed = _shadowing_lane_segments(value)
    if shadowed:
        pytest.skip("this host's lane shadows the standard library, so the "
                    "entry refuses it and front-insertion is NOT MEASURED "
                    "here: " + "; ".join(shadowed))
    return value


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
    for source in [_real_site_dir(), *_site_processing_dirs()]:
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


def _child_env(**extra: str) -> dict:
    """The environment every child below runs under.

    Factored out so the entry-free control in
    `test_a_half_closure_lane_is_not_silently_completed` runs under the IDENTICAL
    environment as the entry it is a control for. A control that differs from its
    subject in a second variable is not a control.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", _HOST_LANE_ENV}
           and not key.startswith(_PROGRESS_ENV_PREFIX)}
    env[_AUTOLOAD_ENV] = "1"
    env.update(extra)
    return env


def _entry(python: Path, subject: Path, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(python), "-I", str(ENTRY), "-q", "-p", "no:cacheprovider",
         "test_ok.py"],
        cwd=subject, env=_child_env(**extra), capture_output=True, text=True)


def _session_without_the_entry(python: Path, subject: Path, lane: Path
                               ) -> subprocess.CompletedProcess:
    """Can this interpreter run the session with ONLY `lane` on `sys.path`?

    Same interpreter, same subject, same environment, same one directory -- and
    no trusted entry. So this measures whether the RUNTIME is viable, which is a
    different question from whether the ENTRY reports it faithfully, and it is
    the question the caller needs answered before it can know which verdict to
    expect.
    """
    return subprocess.run(
        [str(python), "-I", "-c",
         "import sys" + chr(10)
         + "sys.path.insert(0, " + repr(str(lane)) + ")" + chr(10)
         + "import pytest" + chr(10)
         + "raise SystemExit(pytest.main("
           "['-q', '-p', 'no:cacheprovider', 'test_ok.py']))" + chr(10)],
        cwd=subject, env=_child_env(), capture_output=True, text=True)


def _missing_module(text: str) -> str:
    """The `No module named 'x'` line from a child's output, or "" if absent.

    Returning "" rather than guessing keeps "I could not extract a cause" from
    arriving at the caller as "the cause matched".
    """
    for line in text.splitlines():
        marker = line.find("No module named")
        if marker != -1:
            return line[marker:].strip()
    return ""


def test_without_the_lane_a_siteless_isolated_entry_refuses(tmp_path):
    """The unrepaired shape, asserted so the repair has something to be a repair OF."""
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "[NORECORD] trusted pytest entry:" in proc.stderr
    assert "No module named 'pytest'" in proc.stderr


def test_the_named_lane_records_where_the_same_entry_refused(tmp_path):
    """THE REVERT GUARD. Remove the lane from `run()` and this goes red."""
    proc = _entry(_siteless_python(tmp_path), _subject(tmp_path),
                  **{_HOST_LANE_ENV: _require_unshadowed_lane(_closure_lane())})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_the_lane_is_inserted_at_the_front_not_appended(tmp_path):
    """MEASURED: appending mixes the lane's pure-Python against the system's C
    extensions and dies in the mismatch (cffi 2.0.0 vs _cffi_backend 1.15.19).
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
                  **{_HOST_LANE_ENV: _require_unshadowed_lane(_closure_lane())})
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
                  **{_HOST_LANE_ENV: _require_unshadowed_lane(_closure_lane())})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 passed" in proc.stdout, proc.stdout


def test_the_entry_reports_the_runtime_it_was_given_and_never_completes_it(
        tmp_path):
    """A lane naming ONLY the runner's own directory must get the verdict that
    directory actually deserves -- refusal when something is missing, a record
    when nothing is -- and never a refusal papered over by reaching past it.

    WHY THIS IS NOT `if the closure spans one directory`. It was, and that guard
    was wrong. MEASURED on two hosts of this fleet at the same commit:

        8HD-d  runner dir  ~/.local/lib/python3.12/site-packages
               pygments lives in /usr/lib/python3/dist-packages, so the runner
               dir alone is INSUFFICIENT and the entry refuses.       rc 2
        8HD-7  runner dir  ~/.local/lib/python3.10/site-packages
               which already holds everything that session imports, so the
               runner dir alone is SUFFICIENT and the entry records.  rc 0

    Both hosts have a three-directory closure by the `os.pathsep` count, so
    counting directories predicted a refusal on 8HD-7 that could not happen
    there and the test failed on the orchestrator host while passing here --
    which is the host-dependent gate this repository refuses to ship.

    REPRODUCED on 8HD-d before rewriting it, by building a runner directory that
    holds the whole closure and pointing the lane at that alone: the entry
    records, `1 passed`, rc 0 -- 8HD-7's shape, on this host, from the same
    entry. So the ENTRY was never wrong; the guard was measuring a proxy.

    The property is SUFFICIENCY, and sufficiency is measured, not counted:
    `_session_without_the_entry` runs the same interpreter, subject and
    environment with that one directory on `sys.path` and no entry at all. What
    is asserted is that the entry's verdict AGREES with it, which is a real
    claim in both directions:

      control fails, entry records  ->  the entry reached past the lane it was
                                        given, which is the silent fallback
                                        `trusted_pytest_entry`'s own docstring
                                        refuses. THE DEFECT THIS TEST IS FOR.
      control records, entry fails  ->  the entry refuses a runtime that works.

    and on a host whose runner directory is insufficient it additionally pins
    that the refusal names the SAME cause the control hit, rather than a generic
    one.
    """
    python = _siteless_python(tmp_path)
    subject = _subject(tmp_path)
    runner_only = _real_site_dir()

    control = _session_without_the_entry(python, subject, runner_only)
    proc = _entry(python, subject, **{_HOST_LANE_ENV: str(runner_only)})

    if control.returncode == 0:
        assert proc.returncode == 0, (
            "the runner's own directory runs this session with no entry at all, "
            "so the entry had nothing to refuse and refused anyway:\n"
            + proc.stdout + proc.stderr)
        assert "1 passed" in proc.stdout, proc.stdout
        return

    assert proc.returncode == 2, (
        "the runner's own directory CANNOT run this session -- the control "
        f"exited {control.returncode} -- yet the entry recorded, so it resolved "
        "the missing part from somewhere the lane never named:\n"
        + control.stdout + control.stderr + "\n--- entry ---\n"
        + proc.stdout + proc.stderr)
    assert "[NORECORD] trusted pytest entry:" in proc.stderr, proc.stderr

    cause = _missing_module(control.stdout + control.stderr)
    if cause:
        assert cause in proc.stderr, (
            f"the control failed with {cause!r} and the entry refused for some "
            f"other stated reason: {proc.stderr!r}")
    else:
        # NOT a pass. The refusal is still required to SAY something; what could
        # not be done here is the tighter check that it says the RIGHT thing.
        reason = proc.stderr.split("[NORECORD] trusted pytest entry:", 1)[1]
        assert reason.strip(), (
            "the entry refused without stating a cause, and the control's own "
            "failure was not module-shaped so it could not be cross-checked: "
            + repr(control.stdout + control.stderr))


def test_every_named_directory_answers_in_the_order_it_was_named(tmp_path):
    """The widened value is a LIST, not a set and not one directory with noise.

    Asserted from inside the recorded session on `sys.path` itself, because the
    order is the whole contract: the first directory named must answer first,
    which is what keeps the runner resolving from the directory the provenance
    assertions above pin it to.
    """
    subject = _subject(tmp_path)
    value = _require_unshadowed_lane(_closure_lane())
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


# ===========================================================================
# vibe-ic#2231 — A LANE MAY NOT SHADOW THE STANDARD LIBRARY
#
# The lane goes in at position 0. Position 0 is ahead of the stdlib, so a lane
# holding `argparse.py` does not add a runner, it REPLACES a stdlib module for
# every import that follows -- including the runner's own. MEASURED on 8HD-9 at
# live main a003990aef, this module against clean main:
#
#   [NORECORD] trusted pytest entry: ArgumentParser.__init__() got an
#              unexpected keyword argument 'allow_abbrev'
#
#   4 failed, 8 passed, 2 skipped
#
# `argparse 1.4.0` (a PyPI backport predating `allow_abbrev`) sits in that
# host's user site; `import pytest` two lines after the front-insert reaches
# `_pytest.config.argparsing`, which builds `ArgumentParser(allow_abbrev=...)`
# against the shadow. The tier was already honest -- `[NORECORD]`, rc 2, never
# a pass -- but the REASON named a keyword in a file the reader would then go
# and read for nothing. The entry had never measured WHICH module was shadowed,
# so it could not say. 4 test ids, ONE root cause.
#
# These pin the repair: the entry MEASURES the lane's top level against
# `sys.stdlib_module_names` and refuses BY NAME. Nothing is relaxed -- the
# refusal is new and strictly narrower than admitting a poisoned lane.
# ===========================================================================
def _shadow_lane(tmp_path: Path, module: str = "argparse") -> Path:
    """A lane whose top level shadows one stdlib module, and nothing else."""
    lane = tmp_path / "shadowlane"
    lane.mkdir(parents=True, exist_ok=True)
    (lane / f"{module}.py").write_text(
        "raise AssertionError('the stdlib shadow was imported')\n",
        encoding="utf-8")
    return lane


def test_a_lane_that_shadows_the_stdlib_is_refused_BY_NAME(tmp_path):
    """The refusal names the shadowed MODULE and the file, not a downstream
    keyword. This is the #2231 repair: on clean main the same lane produced
    `unexpected keyword argument 'allow_abbrev'`, which sends the reader to
    `_pytest/config/argparsing.py` -- the wrong file entirely."""
    subject = _subject(tmp_path)
    value = os.pathsep.join([str(_shadow_lane(tmp_path)), _closure_lane()])
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: value})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "NORECORD" in combined, combined
    assert "SHADOWS the standard library" in combined, combined
    assert "argparse" in combined, combined
    assert "argparse.py" in combined, combined
    assert str(_shadow_lane(tmp_path)) in combined, combined
    # and it does NOT report the downstream symptom instead
    assert "allow_abbrev" not in combined, combined


def test_the_shadow_refusal_names_EVERY_shadowed_module_not_just_the_first(tmp_path):
    """A lane with two shadows names both. A refusal that stopped at the first
    would send a reader to fix one file and hit the next one."""
    lane = _shadow_lane(tmp_path)
    (lane / "types.py").write_text("raise AssertionError('shadow')\n",
                                   encoding="utf-8")
    subject = _subject(tmp_path)
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: os.pathsep.join(
                      [str(lane), _closure_lane()])})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "argparse" in combined and "types" in combined, combined


def test_a_shadow_the_runner_never_touches_is_refused_too(tmp_path):
    """THE SILENT CASE — and it is why the refusal is a REFUSAL and not just a
    better message.

    The two shadow cases above both use names the runner really imports:
    `argparse` (via `_pytest.config.argparsing`) and `types`. Those fail
    LOUDLY, which is the mild shape — something goes wrong and a reader goes
    looking. This one does not.

    `wave` is a stdlib module pytest's start-up never touches. A lane holding
    `wave.py` sits at position 0 ahead of the standard library for the whole
    session and changes what `import wave` means, and NOTHING in the run says
    so: on an entry without the name-set check this session reports an ORDINARY
    PASS. A trusted entry whose contract is "the import environment is known"
    must not be able to reach that state.

    So this pins that the check is on the NAME SET, not on what happens to
    break. `_shadow_lane` plants a body that raises if imported, which here is
    belt-and-braces: the point is that the refusal arrives WITHOUT the import.
    """
    subject = _subject(tmp_path)
    lane = _shadow_lane(tmp_path, "wave")
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: os.pathsep.join(
                      [str(lane), _unshadowed_closure_lane(tmp_path)])})
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, (
        "a lane shadowing a stdlib name the runner never imports ran a session "
        f"and reported it as ordinary:\n{combined}")
    assert "NORECORD" in combined, combined
    assert "SHADOWS the standard library" in combined, combined
    assert "wave" in combined, combined
    assert "wave.py" in combined, combined
    # the shadow was never imported — the refusal beat it to the interpreter
    assert "the stdlib shadow was imported" not in combined, combined


def test_a_name_NESTED_in_a_package_is_not_a_shadow(tmp_path):
    """Only the TOP LEVEL of a lane is what the import system offers first.
    Refusing on a nested `argparse.py` would refuse most real site directories
    for a file that can never win."""
    lane = tmp_path / "nestedlane" / "pkg"
    lane.mkdir(parents=True)
    (lane / "__init__.py").write_text("", encoding="utf-8")
    (lane / "argparse.py").write_text("x = 1\n", encoding="utf-8")
    subject = _subject(tmp_path)
    value = os.pathsep.join([str(lane.parent),
                             _unshadowed_closure_lane(tmp_path)])
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: value})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_a_clean_lane_is_still_admitted(tmp_path):
    """DIRECTION-1: the new refusal must not refuse a lane that shadows
    nothing. Without this the repair could be 'refuse everything'."""
    lane = tmp_path / "cleanlane"
    lane.mkdir()
    (lane / "not_a_stdlib_name_xyz.py").write_text("x = 1\n", encoding="utf-8")
    subject = _subject(tmp_path)
    value = os.pathsep.join([str(lane),
                             _unshadowed_closure_lane(tmp_path)])
    proc = _entry(_siteless_python(tmp_path), subject,
                  **{_HOST_LANE_ENV: value})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_the_caller_contract_error_still_reports_BEFORE_the_host_condition(tmp_path):
    """ORDERING, pinned. The autoload pin is the CALLER's own error; a shadow is
    a condition of the machine. A caller that forgot the token must be told
    about the token. Ordering the shadow first also cost
    `test_the_lane_refuses_without_the_autoload_pin` its subject on a shadowed
    host, which is how this ordering was found."""
    subject = _subject(tmp_path)
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", _AUTOLOAD_ENV}
           and not key.startswith(_PROGRESS_ENV_PREFIX)}
    env[_HOST_LANE_ENV] = str(_shadow_lane(tmp_path))
    proc = subprocess.run(
        [str(_siteless_python(tmp_path)), "-I", str(ENTRY), "-q", "-p",
         "no:cacheprovider", "test_ok.py"],
        cwd=subject, env=env, capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert _AUTOLOAD_ENV in proc.stderr, proc.stderr
    assert "SHADOWS" not in proc.stderr, proc.stderr
