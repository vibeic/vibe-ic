"""The targeted-arm cache must MISS whenever any input it claims to cover moves.

A cache that misses is slow. A cache that HITS when an input moved is a false
green, and this repo has already paid for one class of those. Every test here
plants exactly one change and asserts the key moved with it — because "the key
covers X" is a claim about behaviour, not a comment.

The end-to-end shape (publish a green record, replay it, plant a defect, watch
the round go red) is covered by the last two tests, which drive the real
program against a real pytest selection in a throwaway git repo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "targeted_arm_cache.py"
RS = "\x1f"


def _run(args, env=None, cwd=None):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True, env=env, cwd=cwd)


@pytest.fixture()
def subject(tmp_path: Path) -> Path:
    """A throwaway repo shaped like this one: repo root, plugin, programs."""
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs" / "tests").mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir()
    (repo / "tools").mkdir()
    (repo / "tools" / "gatekeeper-land.sh").write_text("#!/usr/bin/env bash\n")
    for name in ("pytest_per_file_junit.py", "ci_targeted_test_select.py",
                 "_watchdog.py", "_pytest_progress_plugin.py",
                 "suite_write_guard.py", "scratch_root_guard.py"):
        (plugin / "programs" / name).write_text(f"# {name}\n")
    (plugin / "pytest.ini").write_text("[pytest]\n")
    (plugin / "conftest.py").write_text("# conftest\n")
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}\n')
    (plugin / "programs" / "tests" / "test_one.py").write_text(
        "def test_one():\n    assert True\n")
    (repo / ".gitignore").write_text("*.log\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "init"], check=True)
    sel = tmp_path / "sel.txt"
    sel.write_text("programs/tests/test_one.py\n")
    return repo


def _key(subject: Path, *, selection: Path | None = None,
         pytest_argv: str = "python3\x1f-m\x1fpytest",
         driver_argv: str = "--fallback-jobs\x1f8",
         env: dict | None = None) -> str:
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    sel = selection or (subject.parent / "sel.txt")
    proc = _run(["--repo", str(subject), "--plugin", str(plugin),
                 "--selection", str(sel),
                 f"--pytest-argv={pytest_argv}",
                 f"--driver-argv={driver_argv}", "key"], env=env)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_the_key_is_stable_when_nothing_moves(subject: Path) -> None:
    assert _key(subject) == _key(subject)


@pytest.mark.parametrize("mutate,label", [
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "suite_write_guard.py").write_text("# moved\n"),
     "a tracked source file"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                "test_one.py").write_text("def test_one():\n    assert False\n"),
     "a tracked test file"),
    (lambda r: (r / "tools/gatekeeper-land.sh").write_text("#!/bin/bash\n# moved\n"),
     "the harness"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/conftest.py")
     .write_text("# moved\n"),
     "conftest.py, which no test names in an import"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/pytest.ini")
     .write_text("[pytest]\n# moved\n"),
     "pytest.ini"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/"
                "plugin.json").write_text('{"version": "1.0.1"}\n'),
     "the plugin version"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "untracked_new.py").write_text("# new, untracked\n"),
     "an UNTRACKED new file"),
    (lambda r: (r / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                "fixture.json").write_text("{}\n"),
     "an untracked NON-.py fixture"),
    (lambda r: os.chmod(r / "vibe-ic-marketplace/plugins/vibe-ic/pytest.ini",
                        0o755),
     "a mode change with identical content"),
])
def test_the_key_moves_when_an_input_moves(subject: Path, mutate, label) -> None:
    before = _key(subject)
    mutate(subject)
    assert _key(subject) != before, f"the key did not cover {label}"


def test_the_key_moves_when_an_ignored_but_non_regenerable_file_appears(
        subject: Path) -> None:
    before = _key(subject)
    (subject / "scratch.log").write_text("read by a gate\n")  # matches .gitignore
    assert _key(subject) != before, (
        "an IGNORED file is still an input; only __pycache__/.pyc/.pytest_cache "
        "are exempt, and that exemption is a named list")


def test_regenerable_bytecode_is_exempt(subject: Path) -> None:
    before = _key(subject)
    cache = (subject / "vibe-ic-marketplace/plugins/vibe-ic/programs"
             / "__pycache__")
    cache.mkdir()
    (cache / "x.cpython-310.pyc").write_bytes(b"\x00\x01")
    assert _key(subject) == before, (
        "the suite is allowed to write regenerable bytecode; treating it as an "
        "input would make every key a miss and the cache pointless")


def test_the_key_moves_with_the_pytest_argv(subject: Path) -> None:
    assert _key(subject, pytest_argv="python3\x1f-m\x1fpytest") != _key(
        subject, pytest_argv="python3\x1f-m\x1fpytest\x1f--timeout=180")


def test_the_key_moves_with_the_driver_argv(subject: Path) -> None:
    assert _key(subject, driver_argv="--fallback-jobs\x1f8") != _key(
        subject, driver_argv="--fallback-jobs\x1f16")


def test_the_key_moves_with_the_selection(subject: Path, tmp_path: Path) -> None:
    other = tmp_path / "sel2.txt"
    other.write_text("programs/tests/test_one.py\nprograms/tests/test_two.py\n")
    assert _key(subject, selection=other) != _key(subject)


def test_the_key_moves_with_the_environment(subject: Path) -> None:
    env = dict(os.environ)
    base = _key(subject, env=env)
    env["PLANTED_MARKER"] = "1"
    assert _key(subject, env=env) != base


def test_an_ephemeral_output_path_does_not_move_the_key(subject: Path) -> None:
    """--junit names an OUTPUT. Keeping the mktemp path would make two
    identical runs miss each other, which is how the first draft failed."""
    a = _key(subject, driver_argv="--junit\x1f/tmp/aaa.xml\x1f--fallback-jobs\x1f8")
    b = _key(subject, driver_argv="--junit\x1f/tmp/bbb.xml\x1f--fallback-jobs\x1f8")
    assert a == b
    c = _key(subject, driver_argv="--fallback-jobs\x1f8")
    assert a != c, "dropping the flag entirely must still move the key"


def test_a_missing_instrument_is_a_refusal_not_a_hit(subject: Path,
                                                     tmp_path: Path) -> None:
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs" / "_watchdog.py").unlink()
    proc = _run(["--repo", str(subject), "--plugin", str(plugin),
                 "--selection", str(tmp_path / "sel.txt"),
                 "--cache", str(tmp_path / "cache"),
                 "--pytest-argv=x", "--driver-argv=y", "lookup"])
    assert proc.returncode == 1, "an unreadable input must be a MISS"
    assert "CACHE_REFUSE" in proc.stderr or "CACHE_MISS" in proc.stderr


def test_a_red_record_is_never_published(subject: Path, tmp_path: Path) -> None:
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    cache = tmp_path / "cache"
    junit = tmp_path / "j.xml"
    junit.write_text(
        '<testsuites><testsuite name="s" tests="1">'
        '<testcase classname="c" name="n" file="programs/tests/test_one.py">'
        '<failure message="boom"/></testcase></testsuite></testsuites>')
    log = tmp_path / "l.log"
    log.write_text("AGGREGATE_COMPLETE rc=1\n")
    proc = _run(["--repo", str(subject), "--plugin", str(plugin),
                 "--selection", str(tmp_path / "sel.txt"), "--cache", str(cache),
                 "--pytest-argv=x", "--driver-argv=y", "publish",
                 "--junit", str(junit), "--log", str(log), "--rc", "1"])
    assert proc.returncode == 0
    assert "CACHE_NOPUBLISH" in proc.stderr
    assert not list(cache.glob("*.manifest.json")) if cache.exists() else True


def test_a_record_missing_a_selected_file_is_never_published(
        subject: Path, tmp_path: Path) -> None:
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    cache = tmp_path / "cache"
    junit = tmp_path / "j.xml"
    junit.write_text(
        '<testsuites><testsuite name="s" tests="1">'
        '<testcase classname="c" name="n" file="programs/tests/test_other.py"/>'
        '</testsuite></testsuites>')
    log = tmp_path / "l.log"
    log.write_text("AGGREGATE_COMPLETE rc=0\n")
    proc = _run(["--repo", str(subject), "--plugin", str(plugin),
                 "--selection", str(tmp_path / "sel.txt"), "--cache", str(cache),
                 "--pytest-argv=x", "--driver-argv=y", "publish",
                 "--junit", str(junit), "--log", str(log), "--rc", "0"])
    assert "CACHE_NOPUBLISH" in proc.stderr
    assert not (cache.exists() and list(cache.glob("*.manifest.json")))


def test_publish_then_lookup_round_trips_and_a_planted_defect_misses(
        subject: Path, tmp_path: Path) -> None:
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    cache = tmp_path / "cache"
    junit = tmp_path / "j.xml"
    junit.write_text(
        '<testsuites><testsuite name="s" tests="1">'
        '<testcase classname="c" name="n" file="programs/tests/test_one.py"/>'
        '</testsuite></testsuites>')
    log = tmp_path / "l.log"
    log.write_text("AGGREGATE_COMPLETE rc=0\n")
    common = ["--repo", str(subject), "--plugin", str(plugin),
              "--selection", str(tmp_path / "sel.txt"), "--cache", str(cache),
              "--pytest-argv=x", "--driver-argv=y"]
    assert _run([*common, "publish", "--junit", str(junit), "--log", str(log),
                 "--rc", "0"]).returncode == 0
    hit = _run([*common, "lookup", "--out-junit", str(tmp_path / "out.xml")])
    assert hit.returncode == 0 and "CACHE_HIT" in hit.stderr
    assert (tmp_path / "out.xml").read_text() == junit.read_text()

    (plugin / "programs" / "suite_write_guard.py").write_text("# planted\n")
    miss = _run([*common, "lookup"])
    assert miss.returncode == 1, "a planted defect must not be served from cache"
    assert "CACHE_MISS" in miss.stderr


def test_the_manifest_names_every_input_class(subject: Path,
                                              tmp_path: Path) -> None:
    """A key nobody can audit is a key nobody can trust."""
    plugin = subject / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    man = tmp_path / "m.json"
    proc = _run(["--repo", str(subject), "--plugin", str(plugin),
                 "--selection", str(tmp_path / "sel.txt"),
                 "--pytest-argv=x", "--driver-argv=y", "key",
                 "--manifest", str(man)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(man.read_text())
    for field in ("schema", "subject_sha256", "selection_sha256",
                  "pytest_argv", "driver_argv", "instrument", "runtime",
                  "host"):
        assert field in payload, field
    for field in ("harness", "driver", "selector", "watchdog",
                  "progress_plugin", "write_guard", "scratch_guard",
                  "pytest_ini", "plugin_json", "self", "conftests"):
        assert field in payload["instrument"], field
    for field in ("python_version", "python_exe_sha256", "distributions_sha256",
                  "pinned_packages_sha256", "environ_sha256", "umask",
                  "uid_gid"):
        assert field in payload["runtime"], field
    for field in ("node", "machine_id", "boot_id"):
        assert field in payload["host"], field


def test_a_counter_of_what_the_key_ignores_is_not_in_the_key(subject: Path) -> None:
    """Regression: the first draft hashed `subject_counts`, one member of which
    counts the regenerable paths the key deliberately SKIPS. It grows as the
    suite writes __pycache__, so two rounds on an identical tree produced
    different keys (887c33e2... vs e50d4a3d..., differing in that field alone)
    and the second missed its own predecessor."""
    before = _key(subject)
    for i in range(5):
        d = (subject / "vibe-ic-marketplace/plugins/vibe-ic/programs"
             / f"pkg{i}" / "__pycache__")
        d.mkdir(parents=True)
        (d / "m.cpython-310.pyc").write_bytes(b"\x00")
    assert _key(subject) == before
