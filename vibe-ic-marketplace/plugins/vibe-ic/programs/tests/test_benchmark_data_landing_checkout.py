"""The landing corpus checkout is one immutable, machine-recorded subject."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
TOOL = REPO / "tools" / "ci" / "benchmark_data_landing_checkout.py"
TEST_OVERRIDE_ENV = "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE"
PRIVATE_REFS = "refs/vibeic/landing-checkout-measure/"

spec = importlib.util.spec_from_file_location(
    "_benchmark_data_landing_checkout", TOOL)
assert spec and spec.loader
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

# Git's completed fetch/index result is the evidence.  A wall-clock expiry is
# neither a stale verdict nor a complete measurement.
pytestmark = pytest.mark.timeout(0)


def test_unset_environment_resolves_the_0530_canonical_checkout(
        corpus, monkeypatch):
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    monkeypatch.setenv("VIBEIC_BENCHMARK_DATA_CHECKOUT", str(corpus["checkout"]))

    assert B._checkout_arg(None) == corpus["checkout"].resolve()


def _git(root: Path, *args: str, check: bool = True):
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True)
    if check:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _commit(root: Path, name: str, value: str) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(value, encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", f"write {name} {value.strip()}")
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def corpus(tmp_path):
    remote = tmp_path / "benchmark-data.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "canonical"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    _git(seed, "config", "user.email", "test@example.invalid")
    _git(seed, "config", "user.name", "test")
    (seed / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _git(seed, "add", ".gitignore")
    _git(seed, "commit", "-q", "-m", "ignore local output")
    first = _commit(seed, "ic/design/v1/result.txt", "one\n")
    second = _commit(seed, "ic/design/v1/result.txt", "two\n")
    _git(seed, "remote", "add", "origin", str(remote.resolve()))
    _git(seed, "push", "-q", "-u", "origin", "main")
    _git(tmp_path, "clone", "-q", str(remote.resolve()), str(checkout))
    return {
        "remote": remote.resolve(),
        "seed": seed,
        "checkout": checkout,
        "first": first,
        "second": second,
    }


def _invoke(corpus, mode: str, *args: str):
    env = os.environ.copy()
    env[TEST_OVERRIDE_ENV] = "1"
    return subprocess.run(
        [sys.executable, str(TOOL), mode,
         "--checkout", str(corpus["checkout"]),
         "--test-expected-origin", str(corpus["remote"]), *args],
        cwd=str(REPO), env=env, capture_output=True, text=True)


def _measure(corpus, record: Path):
    return _invoke(corpus, "measure", "--record", str(record))


def _advance(corpus, value: str = "three\n") -> str:
    sha = _commit(corpus["seed"], "ic/design/v1/result.txt", value)
    _git(corpus["seed"], "push", "-q", "origin", "main")
    return sha


def test_fresh_checkout_publishes_exact_atomic_measurement(corpus, tmp_path):
    record = tmp_path / "measure.json"

    proc = _measure(corpus, record)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(record.read_text(encoding="utf-8")) == {
        "schema": 1,
        "complete": True,
        "sha": corpus["second"],
        "origin": str(corpus["remote"]),
        "path": str(corpus["checkout"].resolve()),
    }
    assert record.stat().st_mode & 0o777 == 0o600
    refs = _git(
        corpus["checkout"], "for-each-ref", "--format=%(refname)",
        PRIVATE_REFS).stdout
    assert refs == "", f"measurement leaked private refs:\n{refs}"
    assert not list(record.parent.glob(record.name + ".tmp.*"))


def test_remote_advance_makes_canonical_checkout_stale_and_norecord(
        corpus, tmp_path):
    new_sha = _advance(corpus)
    record = tmp_path / "stale.json"
    record.write_text('{"old": true}\n', encoding="utf-8")

    proc = _measure(corpus, record)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "[NORECORD]" in proc.stderr
    assert "stale" in proc.stderr
    assert corpus["second"] in proc.stderr and new_sha in proc.stderr
    assert not record.exists(), "a stale prior record survived a refused measure"
    refs = _git(
        corpus["checkout"], "for-each-ref", "--format=%(refname)",
        PRIVATE_REFS).stdout
    assert refs == "", f"refusal leaked private refs:\n{refs}"


@pytest.mark.parametrize("defect", [
    "tracked_dirty", "ignored_dirty", "sparse", "skip_worktree", "replace",
])
def test_noncanonical_checkout_state_refuses_without_a_record(
        corpus, tmp_path, defect):
    checkout = corpus["checkout"]
    if defect == "tracked_dirty":
        (checkout / "ic/design/v1/result.txt").write_text(
            "modified\n", encoding="utf-8")
    elif defect == "ignored_dirty":
        (checkout / "ignored").mkdir()
        (checkout / "ignored" / "leftover.log").write_text(
            "leftover\n", encoding="utf-8")
    elif defect == "sparse":
        _git(checkout, "sparse-checkout", "init", "--cone")
    elif defect == "skip_worktree":
        _git(checkout, "update-index", "--skip-worktree",
             "ic/design/v1/result.txt")
    elif defect == "replace":
        _git(checkout, "replace", "HEAD", "HEAD^")
    record = tmp_path / f"{defect}.json"

    proc = _measure(corpus, record)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "[NORECORD]" in proc.stderr
    assert not record.exists()
    expected = {
        "tracked_dirty": "dirty",
        "ignored_dirty": "dirty",
        "sparse": "sparse",
        "skip_worktree": "skip-worktree",
        "replace": "replace refs",
    }[defect]
    assert expected in proc.stderr


def test_origin_mismatch_refuses_before_fetch(corpus, tmp_path):
    _git(corpus["checkout"], "remote", "set-url", "origin",
         str(tmp_path / "some-other.git"))
    record = tmp_path / "wrong-origin.json"

    proc = _measure(corpus, record)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "origin must be exactly" in proc.stderr
    assert not record.exists()


def test_clean_smudge_filter_cannot_hide_worktree_bytes_from_the_sha(
        corpus, tmp_path):
    """Porcelain-clean is not byte identity when a filter reverses itself."""
    checkout = corpus["checkout"]
    _git(checkout, "config", "user.email", "test@example.invalid")
    _git(checkout, "config", "user.name", "test")
    _git(checkout, "config", "filter.flip.smudge", "sed s/FAIL/PASS/g")
    _git(checkout, "config", "filter.flip.clean", "sed s/PASS/FAIL/g")
    _git(checkout, "config", "filter.flip.required", "true")
    (checkout / ".gitattributes").write_text(
        "audit.txt filter=flip\n", encoding="utf-8")
    (checkout / "audit.txt").write_text("FAIL\n", encoding="utf-8")
    _git(checkout, "add", ".gitattributes", "audit.txt")
    _git(checkout, "commit", "-q", "-m", "filtered audit fixture")
    _git(checkout, "push", "-q", "origin", "main")
    # The worktree now says PASS, while clean(PASS) == the indexed FAIL blob.
    # This is the exact shape where both status and diff --cached are empty.
    (checkout / "audit.txt").write_text("PASS\n", encoding="utf-8")
    assert _git(checkout, "status", "--porcelain").stdout == ""
    record = tmp_path / "filtered.json"

    proc = _measure(corpus, record)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "raw tracked bytes differ" in proc.stderr
    assert "audit.txt" in proc.stderr
    assert not record.exists()


def test_validate_refuses_expected_sha_or_index_mismatch(corpus, tmp_path):
    private = tmp_path / "private"
    _git(corpus["checkout"], "worktree", "add", "-q", "--detach",
         str(private), corpus["second"])
    private_corpus = dict(corpus, checkout=private)

    wrong_sha = _invoke(
        private_corpus, "validate", "--expected-sha", corpus["first"])
    assert wrong_sha.returncode == 2, wrong_sha.stdout + wrong_sha.stderr
    assert "!= expected measured SHA" in wrong_sha.stderr

    (private / "ic/design/v1/result.txt").write_text(
        "staged-different\n", encoding="utf-8")
    _git(private, "add", "ic/design/v1/result.txt")
    wrong_index = _invoke(
        private_corpus, "validate", "--expected-sha", corpus["second"])
    assert wrong_index.returncode == 2, wrong_index.stdout + wrong_index.stderr
    assert "dirty" in wrong_index.stderr or "index differs" in wrong_index.stderr


def test_validate_old_materialized_sha_is_fetchless_after_remote_advances(
        corpus, tmp_path):
    _advance(corpus)
    private = tmp_path / "private-old"
    # Materialize the once-measured object AFTER remote main has advanced.  A2
    # and B2 bind the immutable SHA, not whichever commit the ref names now.
    _git(corpus["checkout"], "worktree", "add", "-q", "--detach",
         str(private), corpus["second"])
    # Make a fetch impossible.  The configured origin string remains exact;
    # validate must use only the already-materialized commit/index.
    unavailable = corpus["remote"].with_name("remote-now-unavailable.git")
    corpus["remote"].rename(unavailable)
    private_corpus = dict(corpus, checkout=private)

    proc = _invoke(
        private_corpus, "validate", "--expected-sha", corpus["second"])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert corpus["second"] in proc.stdout


def test_one_measurement_keeps_two_arms_on_one_sha_across_remote_advance(
        corpus, tmp_path):
    record = tmp_path / "outer-measurement.json"
    measured = _measure(corpus, record)
    assert measured.returncode == 0, measured.stdout + measured.stderr
    sha = json.loads(record.read_text(encoding="utf-8"))["sha"]
    arm_a = tmp_path / "arm-a"
    arm_b = tmp_path / "arm-b"
    _git(corpus["checkout"], "worktree", "add", "-q", "--detach",
         str(arm_a), sha)

    newer = _advance(corpus, "remote moved between arms\n")
    assert newer != sha
    # B is materialized from the OUTER record, never from the ref that moved.
    _git(corpus["checkout"], "worktree", "add", "-q", "--detach",
         str(arm_b), sha)
    for arm in (arm_a, arm_b):
        arm_corpus = dict(corpus, checkout=arm)
        validated = _invoke(
            arm_corpus, "validate", "--expected-sha", sha)
        assert validated.returncode == 0, validated.stdout + validated.stderr
        assert _git(arm, "rev-parse", "HEAD").stdout.strip() == sha

    # A second mutable measurement is not allowed to reinterpret the stale
    # canonical checkout as current; it produces NORECORD instead.
    stale = _measure(corpus, tmp_path / "second-measurement.json")
    assert stale.returncode == 2, stale.stdout + stale.stderr
    assert "stale" in stale.stderr and newer in stale.stderr
