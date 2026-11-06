"""A LEC killed for MEMORY must not report that it ran out of TIME (#2182).

WHAT WENT WRONG
===============
opentitan_aes, 2026-09-07, measured on 8HD-4:

    reports/lec_equivalence_check.json   exhausted_resource: "wall_clock_seconds"
    docker inspect …                     State.OOMKilled = true
    /sys/fs/cgroup/memory.events         oom_kill 1     (memory.max = 51539607552)

The proof was OOM-killed at a 48 GiB cgroup ceiling and the step reported that
its clock had run out. `annotate_step_budget` assigned the literal
``"wall_clock_seconds"`` whenever the ADMISSION budget was spent and never
asked what stopped the process, and the gate then printed a time-shaped remedy
("Re-run the step with a budget it can finish inside") to match. A whole lane
went to "the budget is too small" and would have stayed there.

rc=137 cannot settle it alone: `_CONTAINER_TIMEOUT_RCS` deliberately folds GNU
``timeout``'s ``--kill-after`` SIGKILL and a cgroup OOM kill into one number.
So the memory controller is asked instead, and when it cannot be asked the
answer is ``not_measured`` WITH THE REASON — never the old default.

WHAT THIS FILE LOCKS, one test per direction
============================================
An OOM kill reports memory. A genuine wall-clock stop reports time. An
unreadable probe reports not_measured and says why. And the specific
regression: no rc=137 input may ever produce ``wall_clock_seconds`` unless the
oom_kill counter was READ and was UNCHANGED.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lec_run  # noqa: E402

# The exact bytes /sys/fs/cgroup/memory.events returned for the container that
# ran opentitan_aes's LEC (cgroup v2), read on 2026-09-07.
_REAL_MEMORY_EVENTS = ("low 0\nhigh 0\nmax 1644\noom 2\noom_kill 1\n"
                       "oom_group_kill 0\n")
_REAL_MEMORY_MAX = "51539607552\n"


# --------------------------------------------------------------------------
# the two parsers
# --------------------------------------------------------------------------
def test_the_oom_counter_is_read_off_the_real_cgroup_bytes():
    assert lec_run.parse_oom_kill_count(_REAL_MEMORY_EVENTS) == 1


def test_a_cgroup_text_with_no_oom_line_is_unreadable_not_zero():
    """'Could not read it' is not 'read it and it was zero'."""
    assert lec_run.parse_oom_kill_count("low 0\nhigh 0\n") is None
    assert lec_run.parse_oom_kill_count("") is None


def test_the_memory_ceiling_is_read_and_an_absent_ceiling_is_none():
    assert lec_run.parse_memory_max_bytes(_REAL_MEMORY_MAX) == 51539607552
    # cgroup v2 writes the literal `max` when there is NO limit -- a ceiling
    # that does not exist cannot be the resource that ran out.
    assert lec_run.parse_memory_max_bytes("max\n") is None
    assert lec_run.parse_memory_max_bytes("9223372036854771712\n") is None


# --------------------------------------------------------------------------
# the classifier -- one test per direction
# --------------------------------------------------------------------------
def test_an_oom_kill_reports_memory():
    """DIRECTION 1 -- opentitan_aes's measured shape, exactly."""
    res, why = lec_run.classify_exhausted_resource(
        budget_exhausted=True, stopped=True, returncode=137,
        oom_kill_delta=1, memory_max_bytes=51539607552)
    assert res == lec_run.EXHAUSTED_MEMORY
    assert "oom_kill" in why and "51539607552" in why


def test_a_genuine_wall_clock_stop_reports_time():
    """DIRECTION 2 -- GNU timeout's SIGTERM expiry is unambiguous."""
    res, why = lec_run.classify_exhausted_resource(
        budget_exhausted=True, stopped=True, returncode=124,
        oom_kill_delta=0, memory_max_bytes=51539607552)
    assert res == lec_run.EXHAUSTED_WALL_CLOCK
    assert "124" in why


def test_a_sigkill_with_the_counter_unchanged_reports_time():
    """rc=137 IS the backstop's --kill-after escalation when the memory
    controller was asked and had killed nothing."""
    res, why = lec_run.classify_exhausted_resource(
        budget_exhausted=True, stopped=True, returncode=137,
        oom_kill_delta=0)
    assert res == lec_run.EXHAUSTED_WALL_CLOCK
    assert "UNCHANGED" in why


def test_an_unreadable_probe_reports_not_measured_and_says_why():
    """DIRECTION 3 -- the honest third answer. This is the value the field
    could not previously take, which is why it defaulted to the wrong one."""
    res, why = lec_run.classify_exhausted_resource(
        budget_exhausted=True, stopped=True, returncode=137,
        oom_kill_delta=None)
    assert res == lec_run.EXHAUSTED_NOT_MEASURED
    assert "not measured" in why.lower()
    # It must name BOTH candidates, or the reader still guesses.
    assert "OOM" in why and "backstop" in why


def test_no_rc137_input_may_silently_become_wall_clock():
    """THE REGRESSION PIN. Before #2182 every one of these said
    `wall_clock_seconds`. Only the branch that actually READ the counter and
    found it unchanged may say so now."""
    for delta in (None, 1, 2):
        res, _ = lec_run.classify_exhausted_resource(
            budget_exhausted=True, stopped=True, returncode=137,
            oom_kill_delta=delta)
        assert res != lec_run.EXHAUSTED_WALL_CLOCK, delta


def test_an_oom_outranks_the_admission_budget_even_when_it_is_not_spent():
    """An OOM at ten minutes of a 24 h budget is still a memory exhaustion.
    The old field could not report it at all: with the admission budget unspent
    it was None, so the kill left no trace in the machine-readable report."""
    res, _ = lec_run.classify_exhausted_resource(
        budget_exhausted=False, stopped=True, returncode=137,
        oom_kill_delta=1, memory_max_bytes=51539607552)
    assert res == lec_run.EXHAUSTED_MEMORY


def test_nothing_ran_out_stays_none():
    """NO-LEAK: a run that finished inside its budget names no resource, as
    before."""
    assert lec_run.classify_exhausted_resource(
        budget_exhausted=False, stopped=False, returncode=0,
        oom_kill_delta=0) == (None, "")


def test_a_spent_admission_budget_with_no_kill_names_no_exhausted_resource():
    """#2212: a completed attempt is not a clock stop, even beyond admission."""
    res, why = lec_run.classify_exhausted_resource(
        budget_exhausted=True, stopped=False, returncode=0, oom_kill_delta=0)
    assert res is None
    assert why == ""


# --------------------------------------------------------------------------
# the probe's delta discipline
# --------------------------------------------------------------------------
def _fake_exec(events, memmax, rc=0):
    def _run(_container, cmd, _timeout):
        return (rc, events if "memory.events" in cmd else memmax, "")
    return _run


def test_the_probe_reads_both_numbers_off_the_container():
    got = lec_run.probe_cgroup_memory(
        "c", _fake_exec(_REAL_MEMORY_EVENTS, _REAL_MEMORY_MAX))
    assert got == {"oom_kills": 1, "memory_max_bytes": 51539607552}


def test_a_probe_that_cannot_run_yields_none_not_zero():
    got = lec_run.probe_cgroup_memory("c", _fake_exec("", "", rc=1))
    assert got == {"oom_kills": None, "memory_max_bytes": None}


# --------------------------------------------------------------------------
# end to end through annotate_step_budget
# --------------------------------------------------------------------------
def _budget_with(kill_cause):
    b = lec_run.StepBudget(total_s=1, clock=lambda: 0.0)
    b.record("verilog", "-DYOSYS", 1, 44599.9, True, True,
             kill_cause=kill_cause)
    return b


def test_the_report_names_memory_when_the_attempt_was_oom_killed():
    rep = lec_run.annotate_step_budget(
        {}, _budget_with({"returncode": 137, "oom_kill_delta": 1,
                          "memory_max_bytes": 51539607552}), stopped=True)
    assert rep["exhausted_resource"] == lec_run.EXHAUSTED_MEMORY
    assert rep["exhausted_resource_evidence"]


def test_the_report_says_not_measured_when_no_probe_ran():
    """Every caller predating the probe lands here -- and lands on the honest
    answer, not on the old default."""
    for stopped in (None, True):
        rep = lec_run.annotate_step_budget(
            {}, _budget_with(None), stopped=stopped)
        assert rep["exhausted_resource"] == lec_run.EXHAUSTED_NOT_MEASURED
        assert "no probe identified" in rep["exhausted_resource_evidence"]


# --------------------------------------------------------------------------
# the gate's REMEDY must match the resource
# --------------------------------------------------------------------------
