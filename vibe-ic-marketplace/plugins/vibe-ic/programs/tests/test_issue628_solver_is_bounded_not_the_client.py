"""#628 — the test suite's own solver could consume the whole host.

A single `yosys`, spawned by the plugin's test suite through SymbiYosys, reached
**109 GB RSS** and was still climbing at ~1 GB per 20 s when it was killed. The
125.7 GB host had 3.2 GB left and zero free swap — about a minute from the OOM
killer, on a machine also running four production services. Killing that one
process returned MemAvailable 3.2 GB -> 113.0 GB; `dmesg` showed no OOM kill,
so the kernel never had to choose.

Nothing in the chain bounded it: `run_tests.sh` sets no ulimit, the suite
container was created with `Memory=0` / `MemorySwap=0`, and the sby invocation
carried no memlimit.

THE MECHANISM IS #623 IN A SECOND PLACE. `_run_sby`'s container path was
`docker exec` under a client-side `subprocess.run(timeout=)`, which bounds the
LOCAL CLIENT: the deadline killed the client while sby's yosys carried on inside
the container, unsignalled and unwatched. A formal property that fails to
converge is the EXPECTED behaviour of a solver on a hard instance, and the
runner treated it as if it were bounded.

TWO BOUNDS, BECAUSE THEY STOP DIFFERENT THINGS:

  * the deadline moves INSIDE the container (coreutils `timeout`, the
    `_container_exec` primitive) so an expiry reaches the solver;
  * `ulimit -v` bounds ADDRESS SPACE for sby and every child it spawns. A
    process may lower its own rlimit but never raise it, so yosys cannot
    escape it — and a deadline alone does not help a solver that eats the host
    in less time than its budget.

THE LIMIT IS A SHARE OF THE HOST, NOT A MODEL OF WHAT A PROOF NEEDS. 25% of
MemTotal with a 4 GiB floor: on the 125.7 GB host that is 31.4 GiB, so the
runaway would have stopped near 31 GB with ~95 GB still free; on a small CI box
the floor keeps every proof from failing for want of memory, which is the same
outage from the other end.

AND A SOLVER THAT HITS EITHER BOUND SAYS SO. An anonymous death reads as a tool
crash and sends the reader to the wrong place; the deadline records an
INCONCLUSIVE — the disposition #617 established for a converging-but-exhausted
induction ladder — rather than a disproof.
"""
from __future__ import annotations

import importlib
import subprocess

F = importlib.import_module("formal_property_run")
CE = importlib.import_module("_container_exec")


class _Rec:
    def __init__(self, rc=0, out="", err=""):
        self.rc, self.out, self.err = rc, out, err
        self.argv = None
        self.timeout = None

    def __call__(self, argv, **kw):
        self.argv = argv
        self.timeout = kw.get("timeout")
        return subprocess.CompletedProcess(argv, self.rc, self.out, self.err)


def _sby(tmp_path):
    p = tmp_path / "formal_top.sby"
    p.write_text("[options]\nmode prove\n", encoding="utf-8")
    return p


# ── the limit is derived, overridable, and refuses to guess ────────────────
def test_the_limit_is_a_share_of_the_host():
    """125.7 GB host -> ~31 GiB, so a 109 GB runaway stops with ~95 GB free."""
    kb = F.memory_limit_kb(meminfo="MemTotal:      131799992 kB", env={})
    assert kb == max(F.FORMAL_MEM_FLOOR_KB,
                     int(131799992 * F.FORMAL_MEM_SHARE))
    assert 30 < kb / 1024 / 1024 < 34


def test_a_small_host_gets_the_floor_not_a_useless_share():
    """A share of a 2 GiB CI box would fail every proof for want of memory —
    the same outage from the other end."""
    assert F.memory_limit_kb(meminfo="MemTotal:        2097152 kB",
                             env={}) == F.FORMAL_MEM_FLOOR_KB


def test_an_unreadable_meminfo_emits_NO_limit_rather_than_a_guess(tmp_path):
    """LOAD-BEARING. A guessed bound is a bound nobody can reason about, and
    too low is an outage. None means no `ulimit` is emitted at all."""
    assert F.memory_limit_kb(meminfo="nothing here", env={}) is None
    rec = _Rec()
    F.subprocess.run, orig = rec, F.subprocess.run
    try:
        F.memory_limit_kb.__globals__["memory_limit_kb"]  # keep the name bound
        import unittest.mock as _m
        with _m.patch.object(F, "memory_limit_kb", lambda: None):
            F._run_sby(_sby(tmp_path), tmp_path, "c", 60)
    finally:
        F.subprocess.run = orig
    assert "ulimit -v" not in rec.argv[-1]


def test_an_explicit_zero_disables_the_bound_and_is_not_a_failure_to_derive():
    """"I chose not to bound this" and "I could not tell how much to bound it"
    are different, and both have to stay sayable."""
    assert F.memory_limit_kb(env={"VIBEIC_FORMAL_MEM_LIMIT_KB": "0"}) is None
    assert F.memory_limit_kb(env={"VIBEIC_FORMAL_MEM_LIMIT_KB": "8388608"}) == 8388608
    assert F.memory_limit_kb(env={"VIBEIC_FORMAL_MEM_LIMIT_KB": "nope"}) is None


# ── the bounds reach the solver, not the client ────────────────────────────
def _drive(monkeypatch, tmp_path, rec, timeout=60, container="edа"):
    monkeypatch.setattr(F.subprocess, "run", rec)
    monkeypatch.setattr(F, "memory_limit_kb", lambda: 32952508)
    return F._run_sby(_sby(tmp_path), tmp_path, container, timeout)


def test_the_deadline_is_enforced_inside_the_container(monkeypatch, tmp_path):
    """The whole defect: a client-side deadline never reaches the solver."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=45)
    assert rec.argv[:3] == ["docker", "exec", "edа"]
    assert rec.argv[3:7] == ["timeout", "-k", str(CE.DEFAULT_KILL_GRACE_S), "45"]


def test_the_client_wait_is_strictly_larger_so_the_container_fires_first(
        monkeypatch, tmp_path):
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=45)
    assert rec.timeout == 45 + CE.CLIENT_GRACE_S


def test_the_address_space_bound_precedes_everything_the_solver_runs(
        monkeypatch, tmp_path):
    """`ulimit` must be the FIRST thing in the shell line: set after sby has
    started it bounds nothing, and yosys is a child of sby."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec)
    assert rec.argv[-1].startswith("ulimit -v 32952508; "), rec.argv[-1]


def test_the_solver_command_still_runs(monkeypatch, tmp_path):
    """THE ACCEPT CASE — a bound that also stops the proof is the gate switched
    off from the other end."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec)
    shell = rec.argv[-1]
    assert "sby -f formal_top.sby" in shell
    assert "/foss/tools/bin" in shell
    assert "rm -rf formal_top" in shell


def _ambient(monkeypatch, tmp_path, limit, timeout=60):
    """Drive the ambient (no-container) path and capture what it dispatched."""
    seen = {}

    def _fake(argv, cwd, to):
        seen["argv"], seen["cwd"], seen["timeout"] = argv, cwd, to
        return 0, "[top] DONE (PASS)\n"

    monkeypatch.setattr(F, "_run_group_bounded", _fake)
    monkeypatch.setattr(F, "memory_limit_kb", lambda: limit)
    F._run_sby(_sby(tmp_path), tmp_path, None, timeout)
    return seen


def test_the_ambient_path_carries_the_bound_too(monkeypatch, tmp_path):
    """SUPERSEDES "the ambient path is unchanged".

    That expectation was written on the premise that a rlimit here would land on
    "the caller's own shell". It does not: the shell is one WE spawn and its only
    child is the solver. And the ambient path is not the exotic one — it is the
    path taken whenever the caller is ALREADY inside the vibeic-eda image, where
    `docker` is absent and `sby` is at /usr/local/bin/sby, which is how CI, the
    flow (`container or None`) and every agent run it. Leaving it unbounded is
    what put two 35.6 GB yosys on a 125 GB host and took it off the network.

    The original assertions are KEPT, not relaxed: still no `docker exec` to
    wrap, still the caller's own deadline, still `sby -f <name>` as the command.
    """
    seen = _ambient(monkeypatch, tmp_path, 32952508)
    assert seen["argv"][:2] == ["bash", "-lc"]
    assert seen["argv"][2].startswith("ulimit -v 32952508; "), seen["argv"][2]
    assert seen["argv"][2].endswith("exec sby -f formal_top.sby")
    assert "docker" not in seen["argv"]
    assert seen["timeout"] == 60


def test_the_ambient_path_omits_the_bound_when_none_can_be_derived(
        monkeypatch, tmp_path):
    """Same rule as the container path: no derivable limit means NO `ulimit`,
    never a guessed one."""
    seen = _ambient(monkeypatch, tmp_path, None)
    assert "ulimit" not in seen["argv"][2]
    assert "sby -f formal_top.sby" in seen["argv"][2]


def test_the_ambient_deadline_is_reported_as_inconclusive_not_a_crash(
        monkeypatch, tmp_path):
    """Symmetric with the container path: an anonymous death reads as a tool
    crash and sends the reader to the wrong place."""
    monkeypatch.setattr(F, "memory_limit_kb", lambda: 32952508)
    monkeypatch.setattr(F, "_run_group_bounded",
                        lambda argv, cwd, to: (124, "[top] engine_0\n"))
    out = F._run_sby(_sby(tmp_path), tmp_path, None, 60)
    assert "SOLVER DEADLINE" in out
    assert "INCONCLUSIVE" in out
    assert "not disproved" in out


def test_an_absent_sby_on_the_ambient_path_still_says_so_in_the_transcript(
        monkeypatch, tmp_path):
    """The bound must not SWALLOW the tool's own words.

    Wrapping the command in `bash -lc` changes who reports the absence: the
    shell now says it (`sby: not found`) where a bare argv raised
    FileNotFoundError. Either way the transcript has to carry the tool name and
    the fact, or "no proof ran" becomes unattributable.
    """
    monkeypatch.setattr(F, "memory_limit_kb", lambda: 32952508)
    monkeypatch.setattr(
        F, "_run_group_bounded",
        lambda argv, cwd, to: (127, "bash: line 1: exec: sby: not found\n"))
    out = F._run_sby(_sby(tmp_path), tmp_path, None, 60)
    assert "sby" in out and "not found" in out, out
    assert "SOLVER DEADLINE" not in out, "an absent tool is not a deadline"


def test_a_missing_shell_keeps_the_historic_not_found_message(
        monkeypatch, tmp_path):
    """The last-resort path: if even `bash` cannot be launched, the ambient
    runner still returns the message the rest of the program keys on, rather
    than letting FileNotFoundError escape into the caller."""
    def _boom(argv, cwd, to):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(F, "memory_limit_kb", lambda: 32952508)
    monkeypatch.setattr(F, "_run_group_bounded", _boom)
    out = F._run_sby(_sby(tmp_path), tmp_path, None, 60)
    assert "sby/docker not found on PATH" in out


# ── hitting a bound is INCONCLUSIVE, never a disproof ──────────────────────
def test_the_container_deadline_records_an_honest_disposition(
        monkeypatch, tmp_path):
    """rc 124 is coreutils `timeout`. An anonymous death reads as a tool crash;
    #617 established that an exhausted proof is INCONCLUSIVE, not disproved."""
    out = _drive(monkeypatch, tmp_path, _Rec(rc=124, out="[top] engine_0\n"))
    assert "SOLVER DEADLINE" in out
    assert "INCONCLUSIVE" in out
    assert "not disproved" in out


def test_a_normal_run_gets_no_deadline_note(monkeypatch, tmp_path):
    out = _drive(monkeypatch, tmp_path, _Rec(rc=0, out="[top] DONE (PASS)\n"))
    assert "SOLVER DEADLINE" not in out
    assert "DONE (PASS)" in out


def test_a_real_solver_failure_is_not_relabelled(monkeypatch, tmp_path):
    """rc 1 is sby saying the property FAILED. Only the deadline's own 124 may
    become INCONCLUSIVE — anything else would launder a counterexample."""
    out = _drive(monkeypatch, tmp_path,
                 _Rec(rc=1, out="[top] DONE (FAIL)\n"))
    assert "SOLVER DEADLINE" not in out
    assert "DONE (FAIL)" in out
