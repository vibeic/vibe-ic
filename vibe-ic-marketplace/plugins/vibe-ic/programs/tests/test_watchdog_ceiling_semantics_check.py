#!/usr/bin/env python3
"""Both directions of `watchdog_ceiling_semantics_check`.

A gate that cannot go red is not a gate, so every clean case below has a
one-token mutation beside it that must turn it red — and every red case has the
edit that must clear it. The mutations are chosen so the gate can still LOOK:
no file is deleted and no call is removed, only one value or one call changes.

WHAT MOVED, AND WHY THE RESOLVER TESTS STAYED (vibe-ic#2051, 2026-09-07)
=======================================================================
Until v1.17.98 the gate's headline offence was "a supervised launch declares a
`hard_ceiling_s` below the backstop", on the then-true ground that the
supervisor KILLED at whatever number it was handed. The owner ruled that out:
the ceiling is a RECORDED BUDGET, the job continues past it, and only a
progress stall may stop anything. A bounded ceiling therefore cannot hurt
anyone, and a gate that still refused one would be asserting a defect the code
no longer has.

So every class-(1) case below keeps its TREE and its RESOLVER assertion and
changes only its VERDICT: `BUDGET`, rc 0, with the resolved value printed. That
is deliberate rather than convenient. The resolver is the part that earns the
census — the two headline offences on main were spelled `float(timeout)` and a
local bound, neither a literal — and dropping its coverage because the verdict
softened would leave a caller list that resolves only the easy cases. Each test
still fails if the resolver reads the wrong number.

What became blocking instead is class (0): the PRIMITIVES may not kill on the
clock. That is the mutation that must redden now, and it is driven from both
sides at the end of this file.
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


def _budget_row(out: str, needle: str) -> bool:
    """Is `needle` printed in the DECLARED BUDGETS census?

    Asserting on the census rather than on the whole stdout is what keeps these
    tests honest after the verdict softened: a resolver that silently returned
    None would give rc 0 too, and only the printed value tells the two apart.
    """
    if "--- DECLARED BUDGETS" not in out:
        return False
    section = out.split("--- DECLARED BUDGETS", 1)[1]
    section = section.split("\n---", 1)[0]
    return needle in section


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


def test_a_bounded_ceiling_on_a_supervised_launch_is_a_declared_budget(tmp_path):
    """The mutation of the case above: ONE keyword added, nothing removed.

    It used to be `rc == 1`, "a wall-clock deadline wearing the watchdog's
    clothes". Since vibe-ic#2051 the supervisor cannot stop on it, so it is a
    declared BUDGET: refused by nobody, resolved to 7200, and printed with its
    file and line so the caller census is complete.
    """
    rc, out = _run(_tree(tmp_path, _BOUNDED))
    assert rc == 0, out
    assert "BUDGET 1" in out, out
    assert _budget_row(out, "subject.py:4"), out
    assert _budget_row(out, "7200"), out


def test_the_backstop_is_read_from_the_primitive_not_copied(tmp_path):
    """7200 is a BUDGET against an 86400 backstop and CLEAN against a 3600 one.
    If the gate had hand-copied the number, the second arm could not move —
    which is the drift shape this repo removes one gate at a time. The verdicts
    softened; the comparison they turn on is the same one."""
    rc_a, out_a = _run(_tree(tmp_path / "a", _BOUNDED, backstop="86_400"))
    rc_b, out_b = _run(_tree(tmp_path / "b", _BOUNDED, backstop="3600"))
    assert rc_a == 0 and "BUDGET 1" in out_a, out_a
    assert rc_b == 0 and "BUDGET 0" in out_b, out_b
    assert "CLEAN 1" in out_b, out_b


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
    assert rc == 0, out
    assert _budget_row(out, "900"), out


def test_a_docker_exec_with_a_marker_is_in_the_population(tmp_path):
    body = ("def go(c, cmd):\n"
            "    return _docker_exec(c, cmd, marker='x', hard_ceiling_s=60)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out
    assert "BUDGET 1" in out, out
    assert _budget_row(out, "60"), out


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
    assert rc == 0, out
    assert _budget_row(out, "120"), out


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
    assert rc == 0, out
    assert _budget_row(out, "7200"), out


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


def test_a_min_against_the_backstop_resolves_to_the_smaller_bound(tmp_path):
    """The mutation of the case above: `min` can be BELOW the backstop, and
    swapping one token must move the row from CLEAN to BUDGET. Without this the
    previous test would pass on a resolver that returns the first argument."""
    body = ("import _watchdog as _wd\n"
            "_CEIL = _wd.DEFAULT_HARD_CEILING_S\n"
            "def derived(cells):\n"
            "    return min(_CEIL, 600)\n"
            "def go(cmd, cells):\n"
            "    c = derived(cells)\n"
            "    return _wd.run_supervised(cmd, hard_ceiling_s=c)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out
    assert "BUDGET 1" in out and "CLEAN 0" in out, out
    assert _budget_row(out, "600"), out


# ---------------------------------------------------------------------------
# the exemption, and its refusal
#
# It MOVED with the offence. A ceiling can no longer be refused, so exempting
# one would be an escape hatch from a door that is no longer locked; the tag now
# reads on the offence that remains — a `timeout=` handed to a primitive that
# has none. The two cases are otherwise the pair they always were: a reason
# clears, a bare tag does not.
# ---------------------------------------------------------------------------
def test_an_exemption_with_a_reason_clears_the_offence(tmp_path):
    body = ("import _progress_run as _pr\n"
            "def go(cmd):\n"
            "    # ceiling-exempt: legacy shim, deleted with the caller\n"
            "    return _pr.run(cmd, timeout=30)\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, out
    assert "EXEMPT 1" in out


def test_a_bare_exemption_tag_exempts_nothing(tmp_path):
    body = ("import _progress_run as _pr\n"
            "def go(cmd):\n"
            "    # ceiling-exempt:\n"
            "    return _pr.run(cmd, timeout=30)\n")
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


def test_a_clean_progress_run_call_is_IN_THE_POPULATION(tmp_path):
    """CZT2 — rc 0 is not the same as "counted", and the difference was the
    whole defect.

    A clean `_pr.run` call used to produce NO ROW at all: the primitive was
    counted only when it was an OFFENDER. So converting a
    `subprocess.run(timeout=N)` wall clock to the supervised primitive moved the
    gate's examined-site count by ZERO -- the old call was never in this
    population and the new one was not either. MEASURED: twenty conversions in
    one lane, examined 115 before and 115 after.

    That number is used as a MONOTONICITY check ("never fewer examined sites, a
    shrink means something left supervision"), so a count that cannot RISE when
    supervision spreads cannot FALL when it retreats either. The check was
    answering a question about a population it did not contain.
    """
    body = ("import _progress_run as _pr\n"
            "def go(cmd):\n"
            "    return _pr.run(cmd, capture_output=True)\n")
    root = _tree(tmp_path, body)
    rows, _ = G.scan(root / "programs" if (root / "programs").is_dir() else root)
    prs = [r for r in rows if r.kind == "progress_run"]
    assert len(prs) == 1, [(r.file, r.line, r.kind, r.verdict) for r in rows]
    assert prs[0].verdict == "CLEAN", prs[0]


def test_the_population_GROWS_when_a_wall_clock_becomes_supervised(tmp_path):
    """THE MONOTONICITY THE HEADLINE NUMBER CLAIMS TO CHECK, driven.

    Two trees differing by exactly one converted call site. The examined count
    must go UP by one -- if it does not, the number is inert and a later reader
    comparing it across versions learns nothing.
    """
    before = _tree(tmp_path / "a",
                   "import subprocess\n"
                   "def go(cmd):\n"
                   "    return subprocess.run(cmd, timeout=1800)\n")
    after = _tree(tmp_path / "b",
                  "import _progress_run as _pr\n"
                  "def go(cmd):\n"
                  "    return _pr.run(cmd)\n")

    def examined(root):
        d = root / "programs" if (root / "programs").is_dir() else root
        return len(G.scan(d)[0])

    assert examined(after) == examined(before) + 1, (
        examined(before), examined(after))


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


# ---------------------------------------------------------------------------
# class (0) — THE PRIMITIVE MAY NOT KILL ON THE CLOCK
#
# This is what the gate now blocks on, so it is what has to be driven from both
# sides. Note the subject: these arms write a synthetic `_watchdog.py` /
# `_docker_watchdog.py`, which every other class in this file deliberately
# SKIPS. A pair that scanned the ordinary population could not reach this class
# at all, and the gate would have been "green" on a mechanism nobody looked at.
# ---------------------------------------------------------------------------

def _primitive_tree(tmp_path: Path, wd_body: str = "", dwd_body: str = "") -> Path:
    d = tmp_path / "programs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_watchdog.py").write_text(
        "DEFAULT_HARD_CEILING_S = 86_400\n" + wd_body, encoding="utf-8")
    if dwd_body:
        (d / "_docker_watchdog.py").write_text(dwd_body, encoding="utf-8")
    return d


_LOOP_CLEAN = '''
def supervise(proc, probe, kill_fn, *, stall_grace_s, hard_ceiling_s):
    while True:
        if stalled(proc, stall_grace_s):
            kill_fn(proc, "stalled")
            return "stalled", None
        if elapsed(proc) > hard_ceiling_s:
            record_budget(proc)
'''

_LOOP_KILLS = '''
def supervise(proc, probe, kill_fn, *, stall_grace_s, hard_ceiling_s):
    while True:
        if stalled(proc, stall_grace_s):
            kill_fn(proc, "stalled")
            return "stalled", None
        if elapsed(proc) > hard_ceiling_s:
            kill_fn(proc, "ceiling")
            return "ceiling", None
'''


def test_a_primitive_that_records_the_budget_is_clean(tmp_path):
    rc, out = _run(_primitive_tree(tmp_path, wd_body=_LOOP_CLEAN))
    assert rc == 0, out
    assert "OFFENDER 0" in out, out


def test_a_primitive_that_kills_at_the_ceiling_is_refused(tmp_path):
    """THE MUTATION THE RULING NAMES. Two lines of the case above change; the
    stall kill beside them is untouched, so the gate still has a supervision
    loop to look at and what moved is the ANSWER inside it."""
    rc, out = _run(_primitive_tree(tmp_path, wd_body=_LOOP_KILLS))
    assert rc == 1, out
    assert "OFFENDER 1" in out, out
    assert "_watchdog.py:" in out, out
    assert "RECORDED BUDGET" in out, out


def test_the_stall_kill_alone_is_never_an_offence(tmp_path):
    """THE CONTROL for the mutation above. Both arms call `kill_fn`; only the
    REASON differs. Without this a gate that flagged every `kill_fn(...)` would
    pass the pair above while refusing the one kill that must stay."""
    only_stall = '''
def supervise(proc, kill_fn, *, stall_grace_s):
    if stalled(proc, stall_grace_s):
        kill_fn(proc, "stalled")
    if going_nowhere(proc):
        kill_fn(proc, "aborted")
'''
    rc, out = _run(_primitive_tree(tmp_path, wd_body=only_stall))
    assert rc == 0, out
    assert "OFFENDER 0" in out, out


_DWD_CLEAN = '''
import _watchdog as _wd
def run_docker_supervised(container, cmd, marker, *, hard_ceiling_s=86_400):
    wrapped = supervised_container_command(cmd, "/tmp/p.pid")
    return _wd.run_supervised(["docker", "exec", container, "bash", "-lc",
                               wrapped], hard_ceiling_s=hard_ceiling_s)
'''

_DWD_WRAPS = '''
import _watchdog as _wd
def run_docker_supervised(container, cmd, marker, *, hard_ceiling_s=86_400):
    wrapped = wrap_with_container_timeout(cmd, hard_ceiling_s, pidfile="/tmp/p")
    return _wd.run_supervised(["docker", "exec", container, "bash", "-lc",
                               wrapped], hard_ceiling_s=hard_ceiling_s)
'''

_DWD_ORPHAN_GUARD = '''
import _watchdog as _wd
def run_docker_supervised(container, cmd, marker, *, hard_ceiling_s=86_400):
    wrapped = supervised_container_command(cmd, "/tmp/p.pid")
    return _wd.run_supervised(["docker", "exec", container, "bash", "-lc",
                               wrapped], hard_ceiling_s=hard_ceiling_s)

def probe(container, cmd, timeout=30):
    """A RAW exec under a host bound — the wrap here is the orphan guard."""
    wrapped = wrap_with_container_timeout(cmd, timeout)
    return _wd.run_supervised(["docker", "exec", container, "bash", "-lc",
                               wrapped], hard_ceiling_s=86_400)
'''


def test_the_shared_supervised_dispatch_may_not_wrap_an_outer_clock(tmp_path):
    """The second class-(0) shape: the supervised command SIGKILLed inside the
    container at the same number the launch declares as its budget."""
    rc, out = _run(_primitive_tree(tmp_path, dwd_body=_DWD_WRAPS))
    assert rc == 1, out
    assert "OFFENDER 1" in out, out
    assert "_docker_watchdog.py:" in out, out


def test_the_clock_free_supervised_dispatch_is_clean(tmp_path):
    """The other direction, one call apart from the case above."""
    rc, out = _run(_primitive_tree(tmp_path, dwd_body=_DWD_CLEAN))
    assert rc == 0, out
    assert "OFFENDER 0" in out, out


def test_a_wrap_at_a_DIFFERENT_value_is_the_orphan_guard_and_is_left_alone(
        tmp_path):
    """THE PRECISION CONTROL, and it was measured rather than imagined.

    A rule of "this file contains a wrap AND a supervised launch" reports
    `lec_run._docker`, which really does contain both — a supervised branch with
    no ceiling, and a short-probe fallback at `timeout=30` whose wrap is the
    2026-07-22 orphan guard doing exactly its job. Flagging that would be a
    finding about the wrong branch, and the remedy would reinstate a real leak.

    The offence is the budget spent TWICE: the wrap's deadline must be the same
    expression the launch declares as its ceiling. Here it is not.
    """
    rc, out = _run(_primitive_tree(tmp_path, dwd_body=_DWD_ORPHAN_GUARD))
    assert rc == 0, out
    assert "OFFENDER 0" in out, out


def test_an_absent_primitive_is_not_an_offence(tmp_path):
    """A gate may not reach its refusal through a hole in the corpus. With no
    `_docker_watchdog.py` in the tree at all, class (0) has nothing to say about
    it — "the file is not here" is not "the file kills on a clock"."""
    rc, out = _run(_primitive_tree(tmp_path, wd_body=_LOOP_CLEAN))
    assert not (tmp_path / "programs" / "_docker_watchdog.py").exists()
    assert rc == 0, out
    assert "OFFENDER 0" in out, out
