"""The classifier that carries a named NORECORD as far as the verdict.

WHAT THIS FILE REFUSES
======================
1. **A skip that fires for everybody.** The engine-absence marker alone is NOT
   enough: with the engine reachable, the same output is `MEASURED` and the
   caller's assertion stands. Driven in both directions with a stub engine, so
   the "reachable" arm is not a host accident.
2. **An escape hatch spelled as a string.** A run that PRINTS the marker on a
   host whose engine answers is `MEASURED`. There is no text a candidate can
   emit that converts a working engine into a skip.
3. **A NOT_MEASURED with no reason.** Every non-reachable answer has to name
   WHICH half was missing — the CLI or the daemon — because "not measured" with
   no cause is the disclosure this whole lane already had and could not use.
4. **A blanket amnesty on a docker-less host.** An output that never blamed the
   engine is `MEASURED` no matter what the host looks like.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _hermetic_engine_capability as C  # noqa: E402

_PROG = Path(__file__).resolve().parents[1] / "_hermetic_engine_capability.py"

# The measured bytes, from the pinned image on 88a8bcdf4d. Kept whole rather
# than trimmed to the marker: the classifier has to find its sentence inside a
# real, noisy verifier log, not inside a string somebody tailored for it.
_REAL_NORECORD_LOG = """=== gatekeeper merge-path verification ===
--- repo=/tmp/x/gkverify_repo0  base=main  ref=innocuous_green
[PASS] hermetic Git subject: 137a94f5e7ec
      --- B1 runner said (this is the CAUSE; the lines below are the symptom):
      [NORECORD] hermetic candidate: cannot execute Docker CLI: \
[Errno 2] No such file or directory: 'docker'
      [NORECORD] hermetic landing arm receipt: cannot resolve runner receipt: \
[Errno 2] No such file or directory: '/tmp/x/b1-hermetic-receipt.json'
gatekeeper-verify-merge: B1 arm receipt is NORECORD
"""

# A run that failed for a reason of its OWN. No engine sentence anywhere.
_REAL_RED_LOG = """=== gatekeeper merge-path verification ===
--- rebase=ok  replayed=bedb8e9ed310  tree=cc53c465144f
REFUSE: 1 NEW FAILING TEST(S) THIS BRANCH OWNS
  programs/tests/test_thing.py::test_value_is_one
"""

_REACHABLE = (True, "the container engine is reachable from this process "
                    "('docker', server 29.1.3)")
_ABSENT = (False, "the container engine CLI 'docker' cannot be executed from "
                  "this process: [Errno 2] No such file or directory: 'docker'")


def test_the_marker_alone_is_not_a_skip():
    """CONDITION 2 IS LOAD-BEARING. Same bytes, engine reachable: MEASURED.

    This is the direction that keeps the landing gate's only end-to-end proof
    alive. If it ever flips, the 23 control tests stop running on every host
    that has an engine — which is every host that can land anything.
    """
    status, reason = C.classify(_REAL_NORECORD_LOG, probe=lambda exe: _REACHABLE)
    assert status == C.MEASURED, reason
    assert "defect in the run" in reason


def test_the_marker_with_a_genuinely_absent_engine_is_not_measured():
    status, reason = C.classify(_REAL_NORECORD_LOG, probe=lambda exe: _ABSENT)
    assert status == C.NOT_MEASURED, reason
    assert "the hermetic arms never started" in reason
    assert "No such file or directory" in reason, (
        "NOT_MEASURED without the named cause is the disclosure this module "
        "exists to stop losing")


def test_an_ordinary_red_is_still_red_on_a_host_with_no_engine():
    """NO BLANKET AMNESTY. A failure that never blamed the engine is judged."""
    status, reason = C.classify(_REAL_RED_LOG, probe=lambda exe: _ABSENT)
    assert status == C.MEASURED, reason
    assert "named no container-engine absence" in reason


def test_an_empty_run_is_measured():
    assert C.classify("", probe=lambda exe: _ABSENT)[0] == C.MEASURED


def test_the_marker_is_the_runners_own_words():
    """The sentence is not paraphrased. `hermetic_candidate_runner.Docker.call`
    builds it from an `OSError`; if that text is ever reworded this assertion
    fails and the classifier stops matching, which is the correct outcome for a
    marker that no longer describes anything."""
    runner = (Path(__file__).resolve().parents[5]
              / "tools" / "ci" / "hermetic_candidate_runner.py")
    assert runner.is_file(), runner
    assert 'cannot execute Docker CLI: {exc}' in runner.read_text(
        encoding="utf-8"), (
        "the runner no longer raises the refusal this classifier keys on")
    assert C.ENGINE_ABSENT_MARKER.endswith("cannot execute Docker CLI:")


def _stub_engine(tmp_path, name, body):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_the_probe_measures_a_working_engine_as_reachable(tmp_path):
    """THE PROBE ITSELF, driven both ways, with no dependence on this host."""
    good = _stub_engine(tmp_path, "engine-ok", 'echo 29.1.3\n')
    reachable, reason = C.probe_engine(str(good))
    assert reachable, reason
    assert "29.1.3" in reason


def test_the_probe_names_a_daemon_that_does_not_answer(tmp_path):
    bad = _stub_engine(
        tmp_path, "engine-down",
        'echo "Cannot connect to the Docker daemon at unix:///var/run/'
        'docker.sock." >&2\nexit 1\n')
    reachable, reason = C.probe_engine(str(bad))
    assert not reachable
    assert "exists but the daemon did not answer" in reason
    assert "Cannot connect to the Docker daemon" in reason, (
        "the daemon's own words are the cause; dropping them leaves an "
        "unactionable refusal")


def test_the_probe_names_a_cli_that_is_not_there(tmp_path):
    reachable, reason = C.probe_engine(str(tmp_path / "no-such-engine"))
    assert not reachable
    assert "cannot be executed from this process" in reason


def test_the_probe_names_an_engine_that_hangs(tmp_path):
    slow = _stub_engine(tmp_path, "engine-hang", 'sleep 30\n')
    reachable, reason = C.probe_engine(str(slow), timeout=0.5)
    assert not reachable
    assert "did not answer" in reason


def test_end_to_end_the_cli_separates_the_two_states(tmp_path):
    """The program is usable as a program, and its EXIT CODE tells the two
    states apart — 0 MEASURED, 3 NOT_MEASURED — so a shell consumer can route
    on the classification without parsing prose."""
    log = tmp_path / "run.log"
    log.write_text(_REAL_NORECORD_LOG)

    absent = subprocess.run(
        [sys.executable, str(_PROG), "--output-file", str(log),
         "--docker-bin", str(tmp_path / "no-such-engine")],
        capture_output=True, text=True)
    assert absent.returncode == 3, absent.stdout + absent.stderr
    doc = json.loads(absent.stdout)
    assert doc["status"] == C.NOT_MEASURED
    assert doc["marker_seen"] is True

    good = _stub_engine(tmp_path, "engine-ok", 'echo 29.1.3\n')
    reachable = subprocess.run(
        [sys.executable, str(_PROG), "--output-file", str(log),
         "--docker-bin", str(good)],
        capture_output=True, text=True)
    assert reachable.returncode == 0, reachable.stdout + reachable.stderr
    assert json.loads(reachable.stdout)["status"] == C.MEASURED


def test_the_cli_reads_stdin(tmp_path):
    good = _stub_engine(tmp_path, "engine-ok", 'echo 29.1.3\n')
    r = subprocess.run(
        [sys.executable, str(_PROG), "--docker-bin", str(good)],
        input=_REAL_RED_LOG, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["marker_seen"] is False
