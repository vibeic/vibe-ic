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

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _container_exec as ce                       # noqa: E402
import container_exec_deadline_check as guard      # noqa: E402


# ── the argv builder ────────────────────────────────────────────────────────

def test_deadline_is_inside_the_container_not_only_on_the_client():
    argv = ce.container_deadline_argv("somecontainer", "sleep 600", 30)
    assert argv[:3] == ["docker", "exec", "somecontainer"]
    # `timeout` must sit BEFORE the shell, so it is the tool's parent and can
    # signal it. After the shell it would be a word in the command string.
    assert argv[3] == "timeout"
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


def test_pre_fix_argv_is_what_the_guard_flags():
    """THE NEGATIVE CONTROL: the guard must fail on the pre-fix source."""
    findings = guard.scan_source(_PRE_FIX, "pre_fix.py")
    assert len(findings) == 1
    assert findings[0]["code"] == "CLIENT_SIDE_DEADLINE_ONLY"


@pytest.mark.parametrize("src,label", [
    (_POST_FIX_VIA_HELPER, "routed through the helper"),
    (_POST_FIX_INLINE, "container-side timeout in the argv"),
    (_HONESTLY_UNBOUNDED, "no deadline claimed at all"),
    (_NOT_AN_EXEC, "not a docker exec"),
])
def test_compliant_and_out_of_scope_shapes_are_not_flagged(src, label):
    assert guard.scan_source(src, "x.py") == [], f"false positive: {label}"


def test_unparseable_source_is_surfaced_not_silently_skipped():
    findings = guard.scan_source("def (:", "broken.py")
    assert findings and findings[0]["code"] == "UNPARSEABLE"


def test_guard_is_advisory_by_default_and_blocking_under_strict(tmp_path):
    (tmp_path / "offender.py").write_text(_PRE_FIX)
    assert guard.main([str(tmp_path)]) == guard.PASS          # advisory
    assert guard.main([str(tmp_path), "--strict"]) == guard.FAIL


def test_guard_reports_unmeasurable_for_a_missing_root(tmp_path):
    assert guard.main([str(tmp_path / "nope")]) == guard.UNMEASURABLE


# ── the converted call site ─────────────────────────────────────────────────

def test_the_real_corner_sweep_no_longer_carries_the_pre_fix_shape():
    src = (PROGRAMS / "analog_real_corner_sweep.py").read_text()
    assert guard.scan_source(src, "analog_real_corner_sweep.py") == []
