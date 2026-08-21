#!/usr/bin/env python3
"""`_gh_cli.gh` — the one `gh` invoker, and the encoding that must not drift.

Extracted in v1.8.36 because `open_organic_issue_count` and `org_open_work_poll`
each carried a byte-identical copy — the shape of vibeic-eda#29, where two
copies of `branch_is_ours` gave opposite answers about the same pins.

It shipped WITHOUT a test, and `plugin_full_audit` D1 caught that on the next
landing: `untested non-synth programs: ['_gh_cli']`. A shared module with no
test is worse than two copies with none, because now one silent change moves
every caller at once.

What these pin is the ERROR ENCODING, which is the whole reason the module
exists: a `gh` that is not installed and a `gh` that failed must never reach a
caller as an empty result, or "no open work" and "could not ask" become the same
answer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _gh_cli  # noqa: E402


def test_a_missing_gh_is_127_not_an_empty_result(monkeypatch):
    """The case the module exists for. Returning ("", "") here would let a
    caller report zero open PRs on a machine with no `gh` installed."""
    def boom(*a, **k):
        raise FileNotFoundError(2, "No such file or directory: 'gh'")
    monkeypatch.setattr(_gh_cli.subprocess, "run", boom)
    rc, out, err = _gh_cli.gh(["repo", "list", "x"])
    assert rc == 127
    assert out == ""
    assert "not found" in err


def test_a_timeout_is_126_and_names_itself(monkeypatch):
    """A slow network is the most likely real failure, and the one most likely
    to be mistaken for an empty listing."""
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=1)
    monkeypatch.setattr(_gh_cli.subprocess, "run", slow)
    rc, out, err = _gh_cli.gh(["issue", "list"], timeout=1)
    assert rc == 126
    assert out == ""
    assert "TimeoutExpired" in err


def test_an_oserror_is_126_too(monkeypatch):
    """Anything else that stops the invocation lands in the same bucket rather
    than propagating — callers branch on the rc, not on an exception."""
    def bad(*a, **k):
        raise OSError(12, "Cannot allocate memory")
    monkeypatch.setattr(_gh_cli.subprocess, "run", bad)
    rc, _, err = _gh_cli.gh(["pr", "list"])
    assert rc == 126
    assert "OSError" in err


def test_gh_own_exit_code_and_streams_pass_through(monkeypatch):
    """…or the three tests above are satisfied by a wrapper that always fails.

    A non-zero rc FROM gh (404, auth failure) must arrive as gh's own code with
    its own stderr, not be rewritten into 126/127 — those two mean "we could not
    run it", which is a different fact.
    """
    class R:
        returncode = 1
        stdout = "partial"
        stderr = "HTTP 404"
    monkeypatch.setattr(_gh_cli.subprocess, "run", lambda *a, **k: R())
    rc, out, err = _gh_cli.gh(["api", "repos/x/y"])
    assert (rc, out, err) == (1, "partial", "HTTP 404")


def test_success_passes_through_unchanged(monkeypatch):
    class R:
        returncode = 0
        stdout = '[{"number": 1}]'
        stderr = ""
    monkeypatch.setattr(_gh_cli.subprocess, "run", lambda *a, **k: R())
    assert _gh_cli.gh(["issue", "list"]) == (0, '[{"number": 1}]', "")


def test_the_command_is_prefixed_with_gh_exactly_once(monkeypatch):
    """A caller passes sub-command args; the module supplies the binary. If a
    caller ever had to pass "gh" itself, half of them would and half would not."""
    seen = {}
    class R:
        returncode = 0; stdout = ""; stderr = ""
    def cap(argv, **k):
        seen["argv"] = argv
        return R()
    monkeypatch.setattr(_gh_cli.subprocess, "run", cap)
    _gh_cli.gh(["repo", "list", "vibeic"])
    assert seen["argv"] == ["gh", "repo", "list", "vibeic"]


def test_the_default_timeout_is_generous_enough_to_be_a_real_bound(monkeypatch):
    """Pinned because a too-small default would turn a slow network into a
    stream of 126s that read like outages."""
    seen = {}
    class R:
        returncode = 0; stdout = ""; stderr = ""
    def cap(argv, **k):
        seen["timeout"] = k.get("timeout")
        return R()
    monkeypatch.setattr(_gh_cli.subprocess, "run", cap)
    _gh_cli.gh(["api", "user"])
    assert seen["timeout"] == _gh_cli.DEFAULT_TIMEOUT >= 60
