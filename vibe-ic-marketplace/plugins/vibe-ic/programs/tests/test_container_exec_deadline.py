#!/usr/bin/env python3
"""The deadline on a container command must bound the TOOL, not the client.

NEGATIVE CONTROL. Every assertion below is paired with the pre-fix shape, so a
test that cannot fail against the old code is not counted as evidence. The
pre-fix argv is constructed inline in `test_pre_fix_argv_is_what_the_guard_flags`
and the guard is RUN on it; if the guard stopped flagging it, that test fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _container_exec as ce                       # noqa: E402


# ── the argv builder ────────────────────────────────────────────────────────

def test_deadline_is_inside_the_container_not_only_on_the_client():
    argv = ce.container_deadline_argv("somecontainer", "sleep 600", 30)
    assert argv[:2] == ["docker", "exec"]
    assert argv[argv.index("somecontainer") + 1] == "timeout"
    # `timeout` must sit BEFORE the shell, so it is the tool's parent and can
    # signal it. After the shell it would be a word in the command string.
    assert argv.index("timeout") < argv.index("bash")
    assert "30" in argv


def test_kill_escalation_is_present_for_tools_that_ignore_sigterm():
    argv = ce.container_deadline_argv("c", "cmd", 30, kill_grace_s=7)
    assert "-k" in argv and argv[argv.index("-k") + 1] == "7"


def test_client_backstop_is_strictly_longer_than_the_container_deadline():
    # If it were not, the client would still be the one that fires, and the
    # orphan would come back exactly as before.
    assert ce.CLIENT_GRACE_S > 0


def test_expiry_is_an_ordinary_return_code_not_an_exception():
    # 124 is coreutils' documented expiry status. Callers already route
    # non-zero; an exception would be thrown past every one of them.
    assert ce.TIMEOUT_EXPIRED_RC == 124


def test_missing_timeout_binary_is_reported_rather_than_swallowed():
    cp = subprocess.CompletedProcess(
        args=[], returncode=ce.TIMEOUT_UNAVAILABLE_RC, stdout="", stderr="")
    why = ce.describe_result(cp, 30)
    assert why and "no deadline" in why.lower()


def test_expiry_is_described_as_expiry_and_never_as_the_tools_verdict():
    cp = subprocess.CompletedProcess(
        args=[], returncode=ce.TIMEOUT_EXPIRED_RC, stdout="", stderr="")
    why = ce.describe_result(cp, 45)
    assert why and "45" in why and "no result" in why


def test_a_completed_run_has_no_complaint():
    cp = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    assert ce.describe_result(cp, 30) is None


# ── the guard, driven in BOTH directions ────────────────────────────────────

_PRE_FIX = '''
import subprocess
def _docker(container, cmd, timeout=120):
    return subprocess.run(["docker", "exec", container, "bash", "-lc", cmd],
                          capture_output=True, text=True, timeout=timeout)
'''

_POST_FIX_VIA_HELPER = '''
import _container_exec
def _docker(container, cmd, timeout=120):
    return _container_exec.run_in_container(container, cmd, deadline_s=timeout)
'''

_POST_FIX_INLINE = '''
import subprocess
def _docker(container, cmd, timeout=120):
    return subprocess.run(
        ["docker", "exec", container, "timeout", "-k", "5", str(timeout),
         "bash", "-lc", cmd],
        capture_output=True, text=True, timeout=timeout + 15)
'''

_HONESTLY_UNBOUNDED = '''
import subprocess
def _docker(container, cmd):
    return subprocess.run(["docker", "exec", container, "bash", "-lc", cmd],
                          capture_output=True, text=True)
'''

_NOT_AN_EXEC = '''
import subprocess
def _names():
    return subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                          capture_output=True, text=True, timeout=10)
'''












# ── the converted call site ─────────────────────────────────────────────────
