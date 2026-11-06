"""tests/test_unanchored_process_kill_check.py — the ratchet that keeps a
pattern-based process kill out of the shipped runners, and the identity reap
that replaced it.

MEASURED 2026-08-27. `_docker_watchdog` and `phase3_one_shot_runner` each
reaped a stalled tool with `pkill -TERM/-KILL -f <marker>` — no `-x`, no uid,
no pid, no pgid. `marker` is a path already in the tool's argv, and every run
on a host execs into ONE shared long-lived container, so the pattern matched a
DIFFERENT run's healthy tool and SIGTERMed it. Signature: `rc=143 with ZERO
test failures`, three times in one night (85 s, 17 min, 46 min), no cgroup OOM
in dmesg. Downstream, `lec_run` did not carry 143 in its container-timeout set,
so the stray SIGTERM became a hard FAIL — a healthy design booked as a PROVEN
NON-EQUIVALENCE.

The gate below is verified in BOTH directions: it must go RED on the exact
shipped defect and GREEN on the tree that replaced it. A ratchet only tested on
the good tree cannot tell "detector works" from "detector never fires".
"""
import sys
import shutil
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _docker_watchdog as DW  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

# The two reapers exactly as they shipped at main 40d0e14c. Kept verbatim so
# the gate is exercised against the real defect, not a paraphrase of it.
SHIPPED_DEFECT_DOCKER_WATCHDOG = '''
import shlex, time
def _kill(_proc, reason):
    q = shlex.quote(marker)
    try:
        docker_exec_raw(container, f"pkill -TERM -f {q}", timeout=15)
        time.sleep(min(term_grace_s, 30))
        docker_exec_raw(container, f"pkill -KILL -f {q}", timeout=15)
    except Exception:
        pass
'''

SHIPPED_DEFECT_PHASE3 = '''
import shlex, time
def _kill(_proc, reason):
    q = shlex.quote(marker)
    try:
        _docker_exec_raw(container, f"pkill -TERM -f {q}", timeout=15)
        time.sleep(min(_WATCHDOG_TERM_GRACE_S, 30))
        _docker_exec_raw(container, f"pkill -KILL -f {q}", timeout=15)
    except Exception:
        pass
'''


# ── the ratchet, RED pole ────────────────────────────────────────────────












# ── the ratchet, GREEN pole ──────────────────────────────────────────────






# ── the gate must fail CLOSED ────────────────────────────────────────────






# ── the whole shipped population ─────────────────────────────────────────






# ── the replacement actually selects by identity ─────────────────────────
def test_reap_command_selects_by_identity_not_by_name():
    cmd = DW.reap_command("/tmp/.vibeic-job-abc.pid", "TERM")
    assert "pkill" not in cmd and "killall" not in cmd
    # reads the stamp, and RE-VALIDATES starttime before signalling anything
    assert "/proc/$1/stat" in cmd
    assert 'VCUR=$(__vic_st "$VPID")' in cmd
    assert '[ "$VCUR" = "$VST" ]' in cmd
    assert "VIBEIC_REAP_SKIP pid_reused" in cmd
    # signals the verified root, its ppid-walked descendants, and its group
    assert 'kill -TERM "$VPID" $VKIDS' in cmd
    assert 'kill -TERM -- "-$VPID"' in cmd


def test_reap_refuses_rather_than_falling_back_to_a_pattern():
    """Every refusal path must END the reap. A fallback to the old selector
    would reinstate the defect on exactly the runs where the stamp failed."""
    cmd = DW.reap_command("/tmp/.vibeic-job-abc.pid", "KILL")
    for reason in ("no_stamp", "unreadable", "bad_pid", "bad_starttime",
                   "already_gone", "pid_reused"):
        assert "VIBEIC_REAP_SKIP %s; exit 0" % reason in cmd, reason


def test_reap_command_rejects_an_arbitrary_signal():
    with pytest.raises(ValueError):
        DW.reap_command("/tmp/x.pid", "HUP; rm -rf /")


def test_the_stamp_records_pid_and_starttime_before_exec():
    pf = DW.new_job_pidfile()
    w = DW.wrap_with_container_timeout("yosys -s x.ys", 3600, pidfile=pf)
    assert w.index("printf") < w.index("exec timeout"), (
        "the identity must be stamped BEFORE the tool replaces the shell")
    assert '"$$"' in w and "__vic_st $$" in w
    assert pf in w


def test_pidfiles_are_unique_per_invocation():
    assert len({DW.new_job_pidfile() for _ in range(200)}) == 200


def test_wrap_without_a_pidfile_is_byte_identical_to_before():
    """Every existing caller keeps its exact command string."""
    assert DW.wrap_with_container_timeout("X", 86400) == (
        "if command -v timeout >/dev/null 2>&1; then "
        "exec timeout --kill-after=5 86395 bash -lc X; "
        "else exec bash -lc X; fi")


def test_reaped_pids_ignores_the_image_login_banner():
    """The vibeic-eda image prints `[INFO] ...` on every login shell, and the
    two runners that reach this code do not set IIC_OSIC_TOOLS_QUIET."""
    assert DW.reaped_pids(
        "[INFO] Final PATH variable: /foo\nVIBEIC_REAP TERM 71 100 \n"
    ) == {71, 100}


# ── the duplicate is gone: ONE implementation, not two ───────────────────
def test_phase3_delegates_the_reap_instead_of_reimplementing_it():
    """ONE producer for the in-container wrap, and NO clock on the supervised
    path. Two byte-equivalent copies of a string is one defect in two files:
    fixing either alone leaves the other live, which is exactly how this one
    survived.

    WHAT THIS TEST USED TO ASSERT, AND WHY IT MOVED (vibe-ic#2099).  It required
    two literals in phase3's source, `_dwd.kill_supervised_job(` and
    `_dwd.wrap_with_container_timeout(`, and then read a `def _kill` closure out
    of that source by index.  All three went stale at once, for two DIFFERENT
    reasons, which is why the red was hard to read:

      * The reap and the closure: v1.18.43 deleted phase3's private `_kill`
        entirely and moved the dispatch to `_docker_watchdog.
        run_docker_supervised`, which does the reap itself.  Delegation became
        MORE complete and the source probe could see LESS of it -- so the
        assertion failed on the tree that satisfied its own docstring best.
      * The wrap: `git show 460a0ffc3` settles where that single call lived --
        the SUPERVISED path, as the outer clock #2051 removed.  So the literal
        went away with the clock, and the assertion was pinning a contract the
        ruling had deliberately retired.

    But the second literal was ALSO, by accident, the only thing in the repo
    standing near a real defect: `_docker_exec_raw` had ALWAYS inlined its own
    copy of that wrap string, byte for byte identical to the helper.  Deleting
    the assertion would have deleted the only pressure on that duplication.  So
    it is not deleted -- it is aimed at the RAW path, where the duplication
    actually was, and paired with the clock property in the place the ruling put
    it.  Nothing here is loosened: the file goes from three source literals to
    one behavioural comparison plus two source guards that each kill a mutation.
    """
    src = (PROG / "phase3_one_shot_runner.py").read_text()

    # (a) ONE PRODUCER, ASKED OF THE RUNNING CODE.  `_docker_exec_raw` must hand
    #     the container the string the shared helper builds -- not a copy of it
    #     that happens to agree today.  Compared against the helper called with
    #     the SAME normalisation the runner applies first, so this is the real
    #     command and not a re-typed guess at it.
    seen = []

    class _CP:
        returncode, stdout, stderr = 0, "", ""

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R.subprocess, "run",
                   lambda argv, **_kw: (seen.append(list(argv)), _CP())[1])
        mp.setattr(shutil, "which", lambda n, *a, **k: None)   # local route:
        mp.setattr(R, "_LOCAL_EXEC_MODE", None, raising=False)   # no host read
        R._docker_exec_raw("cz2099_no_such_container", "yosys -V", timeout=600)
    assert seen, "the raw entry point launched nothing"
    launched = seen[-1][-1]
    assert launched == DW.wrap_with_container_timeout(
        R._tool_status_not_the_log_sinks("yosys -V"), 600), (
        "`_docker_exec_raw` is not building its in-container command through "
        "`_docker_watchdog.wrap_with_container_timeout`: it launched %r"
        % (launched,))

    # (b) AND EXACTLY ONE SHIPPED PROGRAM BUILDS THAT STRING.  (a) passes just
    #     as well against a re-inlined byte-identical copy -- that is precisely
    #     how this duplication survived -- so the PRODUCER SET is asserted, the
    #     same way `test_only_one_module_implements_the_reap` below does it for
    #     the reap.  Keyed on the CONSTRUCTION (`… --kill-after=5 {`, with the
    #     interpolation) and not on the bare literal: `_watchdog.py` and
    #     `watchdog_ceiling_semantics_check.py` both quote a measured `ps` line
    #     containing `timeout --kill-after=5 86395` in their DOCSTRINGS, and a
    #     check that cannot tell prose from code would name them as offenders.
    builders = [f.name for f in sorted(PROG.glob("*.py"))
                if "exec timeout --kill-after=5 {" in f.read_text()]
    assert builders == ["_docker_watchdog.py"], (
        "more than one shipped program builds the container-timeout wrap: %s. "
        "There is one producer, `_docker_watchdog.wrap_with_container_timeout`; "
        "a second copy means the `--kill-after` escalation, the margin and the "
        "no-`timeout`-binary fallback have to be edited twice." % (builders,))
    assert "_dwd.wrap_with_container_timeout(" in src, (
        "phase3 must reach that producer by name")

    # (c) NO CLOCK ON THE SUPERVISED PATH (#2051) -- where the retired literal
    #     used to be, so the property it guarded is kept rather than dropped.
    #     A long tool run is stopped by the progress-stall reap and by nothing
    #     else; the ceiling is a recorded budget.  The RAW path above keeps its
    #     deadline on purpose: a short bounded probe is a different contract.
    dispatched = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R._dwd, "run_docker_supervised",
                   lambda container, cmd, marker, **kw:
                   (dispatched.append(cmd), (0, "", ""))[1])
        R._docker_exec("cz2099_no_such_container", "openroad -exit r.tcl",
                       timeout=600, marker="r.tcl")
    assert dispatched, "the supervised entry point dispatched nothing"
    assert "timeout" not in dispatched[-1], (
        "an outer clock is back on the supervised path: %r" % (dispatched[-1],))
    assert "--kill-after" not in dispatched[-1], dispatched[-1]

    # (d) AND THE REAP IS STILL NOT REBUILT HERE.  The closure this used to read
    #     by index is gone; what must stay gone is phase3 composing a kill
    #     command of its own.
    assert "pkill" not in src, "phase3 is building its own kill command again"


def test_only_one_module_implements_the_reap():
    impls = [p for p in sorted(PROG.glob("*.py"))
             if "_REAP_TAIL" in p.read_text()]
    assert [p.name for p in impls] == ["_docker_watchdog.py"]




# ── AND SOMETHING OTHER THAN THIS FILE HAS TO RUN IT ─────────────────────────
#
# MEASURED 2026-08-28. Every assertion above proves the DETECTOR. None of them
# proved that anything points it at the shipped tree, and nothing did:
# `checker_execution_wiring_audit` — itself a blocking hygiene gate — reported
#
#     [FAIL] 1 checker(s) that NOTHING but their own test runs — a fixture the
#            author wrote proves the logic, never the artefacts:
#              unanchored_process_kill_check.py
#
# and exited 1 on `main` at ae5cc4dbf. A checker only its own test runs is the
# weakest runner class there is: the fixtures below can never regress, because
# they are frozen strings in this file, while the tree they are a proxy for
# changes every day. The gate is now dispatched from `repo_hygiene_gates.sh`,
# and these two tests are what keeps that true — deleting the `run` line would
# otherwise only be visible in the audit's own output.
