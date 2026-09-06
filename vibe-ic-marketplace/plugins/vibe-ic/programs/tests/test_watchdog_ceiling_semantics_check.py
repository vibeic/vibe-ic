#!/usr/bin/env python3
"""Both directions of `watchdog_ceiling_semantics_check`.

A gate that cannot go red is not a gate, so every clean case below has a
one-token mutation beside it that must turn it red — and every red case has the
edit that must clear it. The mutations are chosen so the gate can still LOOK:
no file is deleted and no call is removed, only the ceiling's VALUE changes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import watchdog_ceiling_semantics_check as G   # noqa: E402

GATE = PROGRAMS / "watchdog_ceiling_semantics_check.py"


def _tree(tmp_path: Path, body: str, backstop: str = "86_400") -> Path:
    """A synthetic programs/ dir: the primitive that DECLARES the backstop,
    plus one subject file."""
    d = tmp_path / "programs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_watchdog.py").write_text(
        f"DEFAULT_HARD_CEILING_S = {backstop}\n", encoding="utf-8")
    (d / "subject.py").write_text(body, encoding="utf-8")
    return d


def _run(d: Path):
    cp = subprocess.run(
        [sys.executable, str(GATE), "--programs-dir", str(d), "--table"],
        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ---------------------------------------------------------------------------
# class (1) — a bounded ceiling on a supervised launch
# ---------------------------------------------------------------------------
_CLEAN = """
import _watchdog as _wd
def go(cmd):
    return _wd.run_supervised(cmd, stall_grace_s=1800)
"""

_BOUNDED = """
import _watchdog as _wd
def go(cmd):
    return _wd.run_supervised(cmd, stall_grace_s=1800, hard_ceiling_s=7200)
"""


def test_a_supervised_launch_with_no_ceiling_is_clean(tmp_path):
    rc, out = _run(_tree(tmp_path, _CLEAN))
    assert rc == 0, out
    assert "OFFENDER 0" in out


def test_a_bounded_ceiling_on_a_supervised_launch_is_an_offence(tmp_path):
    """The mutation of the case above: ONE keyword added, nothing removed."""
    rc, out = _run(_tree(tmp_path, _BOUNDED))
    assert rc == 1, out
    assert "subject.py:4" in out
    assert "7200" in out


def test_the_backstop_is_read_from_the_primitive_not_copied(tmp_path):
    """7200 is an offence against an 86400 backstop and CLEAN against a 3600
    one. If the gate had hand-copied the number, the second arm could not
    move — which is the drift shape this repo removes one gate at a time."""
    rc_a, _ = _run(_tree(tmp_path / "a", _BOUNDED, backstop="86_400"))
    rc_b, out_b = _run(_tree(tmp_path / "b", _BOUNDED, backstop="3600"))
    assert rc_a == 1
    assert rc_b == 0, out_b


@pytest.mark.parametrize("value", ["float('inf')", "86_400", "100_000",
                                   "math.inf"])
def test_a_ceiling_at_or_above_the_backstop_is_clean(tmp_path, value):
    body = ("import math\nimport _watchdog as _wd\n"
            f"def go(cmd):\n    return _wd.run_supervised(cmd, "
            f"hard_ceiling_s={value})\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out


def test_a_module_constant_ceiling_is_resolved(tmp_path):
    body = ("import _watchdog as _wd\n_BUDGET = 900\n"
            "def go(cmd):\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=_BUDGET)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out
    assert "900" in out


def test_a_docker_exec_with_a_marker_is_in_the_population(tmp_path):
    body = ("def go(c, cmd):\n"
            "    return _docker_exec(c, cmd, marker='x', hard_ceiling_s=60)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out


def test_a_docker_exec_without_a_marker_is_not_in_the_population(tmp_path):
    """No marker means the SHORT raw-probe path -- a different, bounded
    mechanism that `loop_watchdog_compliance_check` judges. Flagging it here
    would make this gate a second opinion on someone else's population."""
    body = ("def go(c, cmd):\n"
            "    return _docker_exec(c, cmd, timeout=60)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out


# ---------------------------------------------------------------------------
# A BOUND IS A BOUND WHATEVER ITS SPELLING — the four shapes the two headline
# offences on main were actually written in. A resolver that reads only
# literals DROPS all four, and a report that lists neither the offence nor a
# skip tells a reader nothing was skipped.
# ---------------------------------------------------------------------------
def test_a_parameter_default_is_a_bound(tmp_path):
    """`lec_run._docker(..., timeout=120, ...)` then
    `hard_ceiling_s=float(timeout)` — not a Constant at the call site and not a
    module constant. This is the exact shape of the site that was about to kill
    a live 5360 s Yosys proof."""
    body = ("import _watchdog as _wd\n"
            "def go(cmd, timeout=120, marker=None):\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=float(timeout))\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out
    assert "120" in out


def test_a_parameter_with_no_default_stays_unjudged(tmp_path):
    """The other side of the same rule: a forwarded parameter genuinely cannot
    be decided here, and must be DISCLOSED rather than guessed either way."""
    body = ("import _watchdog as _wd\n"
            "def go(cmd, hard_ceiling_s):\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=hard_ceiling_s)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert "UNJUDGED 1" in out
    assert rc == 0, out


def test_an_env_budget_is_judged_by_its_default(tmp_path):
    """`VIBE_IC_DRC_BUDGET_S` with a "7200" default: the value every run
    WITHOUT the variable gets is the shipped behaviour, so that is what is
    judged."""
    body = ("import os\nimport _watchdog as _wd\n"
            "def budget():\n"
            "    return float(os.environ.get('VIBE_IC_X_BUDGET_S', '7200'))\n"
            "def go(cmd):\n"
            "    b = budget()\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=b)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out
    assert "7200" in out


def test_a_max_against_the_backstop_is_clean(tmp_path):
    """`_pnr_hard_ceiling_s` returns `max(_WATCHDOG_HARD_CEILING_S, ...)` — it
    can never be BELOW the backstop, so it is a backstop used as one. The gate
    must resolve that rather than list a correct site as unjudged forever."""
    body = ("import _watchdog as _wd\n"
            "_CEIL = _wd.DEFAULT_HARD_CEILING_S\n"
            "def derived(cells):\n"
            "    return max(_CEIL, cells * 6)\n"
            "def go(cmd, cells):\n"
            "    c = derived(cells)\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=c)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out
    assert "UNJUDGED 0" in out


def test_a_min_against_the_backstop_is_still_an_offence(tmp_path):
    """The mutation of the case above: `min` can be BELOW the backstop, and
    swapping one token must flip the verdict. Without this the previous test
    would pass on a resolver that returns the first argument."""
    body = ("import _watchdog as _wd\n"
            "_CEIL = _wd.DEFAULT_HARD_CEILING_S\n"
            "def derived(cells):\n"
            "    return min(_CEIL, 600)\n"
            "def go(cmd, cells):\n"
            "    c = derived(cells)\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=c)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out
    assert "600" in out


# ---------------------------------------------------------------------------
# the exemption, and its refusal
# ---------------------------------------------------------------------------
def test_an_exemption_with_a_reason_clears_the_offence(tmp_path):
    body = ("import _watchdog as _wd\n"
            "def go(cmd):\n"
            "    # ceiling-exempt: a fixed 5 s liveness probe, no verdict\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=5)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out
    assert "EXEMPT 1" in out


def test_a_bare_exemption_tag_exempts_nothing(tmp_path):
    body = ("import _watchdog as _wd\n"
            "def go(cmd):\n"
            "    # ceiling-exempt:\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=5)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out


# ---------------------------------------------------------------------------
# the unjudgeable are PRINTED, never silently cleared
# ---------------------------------------------------------------------------
def test_an_unresolvable_ceiling_is_reported_not_swallowed(tmp_path):
    """"Could not read it" is not "read it and it was fine". The value below is
    a parameter, so no static resolver can decide it; the gate must say so by
    file and line rather than let a clean verdict imply it looked."""
    body = ("import _watchdog as _wd\n"
            "def go(cmd, ceiling):\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=ceiling)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert "UNJUDGED 1" in out
    assert "subject.py:3" in out
    assert "UNJUDGED (printed, never silently cleared)" in out
    # It does not BLOCK: an unjudged row is a disclosure, not a finding.
    assert rc == 0, out


# ---------------------------------------------------------------------------
# class (2) — a timeout handed to a primitive that has no such parameter
# ---------------------------------------------------------------------------
def test_a_timeout_to_the_progress_run_primitive_is_an_offence(tmp_path):
    body = ("import _progress_run as _pr\n"
            "def go(cmd):\n"
            "    return _pr.run(cmd, capture_output=True, timeout=3600)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out
    assert "TypeError" in out


def test_a_progress_run_call_without_a_timeout_is_clean(tmp_path):
    body = ("import _progress_run as _pr\n"
            "def go(cmd):\n"
            "    return _pr.run(cmd, capture_output=True)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out


def test_the_alias_is_resolved_not_assumed(tmp_path):
    """`import _progress_run as anything` — the offence is the MODULE, not the
    spelling a file happened to import it under."""
    body = ("import _progress_run as weird_name\n"
            "def go(cmd):\n"
            "    return weird_name.run(cmd, timeout=10)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, out


def test_a_same_named_method_on_an_unrelated_object_is_not_flagged(tmp_path):
    """`something_else.run(..., timeout=…)` is an ordinary bounded call and
    belongs to `ci_harness_timeout_ceiling_check`'s population, not this one."""
    body = ("import subprocess\n"
            "def go(cmd):\n"
            "    return subprocess.run(cmd, timeout=10)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out


# ---------------------------------------------------------------------------
# THE ENFORCEMENT ITSELF — the real tree must be clean.
# ---------------------------------------------------------------------------
def test_the_shipped_programs_tree_has_no_wallclock_bounded_supervision():
    rc = G.main(["--programs-dir", str(PROGRAMS)])
    assert rc == 0, (
        "a supervised launch is bounded by a wall clock again — run "
        "`watchdog_ceiling_semantics_check.py --table` for the census")
