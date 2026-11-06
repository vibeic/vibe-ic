"""vibe-ic#2113 O2 — the at-speed producer spent its WALL BUDGET as a GRACE.

`transition_fault_atpg_run._run_in_docker` launched every one of its container
commands as

    res = _wd.run_host_supervised(docker_cmd, stall_grace_s=float(timeout), ...)

and `timeout` is the caller's BUDGET. `_run_batch` hands it
`max(30, int(wall))`, where `wall = _scaled_wall_budget(timeout, scan_flops)`
starts at 1800 s and grows with the design's flop count. Two different
quantities were sharing one number, and spending one as the other cost both:

  * THE BUDGET WAS RECORDED NOWHERE. No `hard_ceiling_s` was passed, so the
    number the run was sized against never reached the record and a reader
    could not tell a run that crossed it from one that never came near. Since
    vibe-ic#2051 a ceiling stops nothing — which is exactly what makes it safe
    to pass, and what makes leaving it out a deleted number rather than a
    removed clock.
  * THE STILLNESS WINDOW BECAME WHATEVER THE BUDGET HAPPENED TO BE — 1800 s
    and up for the SAT batch, 120 s for the solver probe, 60 s for a `fault
    cut`. The number that decides "is this job hung" was never anybody's
    answer to that question; it was a runtime estimate reused for a question
    about stillness.

THE ASSERTIONS HERE ARE ON NON-DEFAULT VALUES ON PURPOSE (the vacuous
`== default` trap, vibe-ic#2097): every number this file checks is chosen so
that it can equal neither `_watchdog.DEFAULT_STALL_GRACE_S` nor
`DEFAULT_HARD_CEILING_S`, and `test_the_probe_values_are_not_the_defaults`
re-derives that fact rather than trusting the comment.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import transition_fault_atpg_run as TDF     # noqa: E402
import fault_atpg_run as F                  # noqa: E402
import _watchdog as W                       # noqa: E402
import _eda_pin                            # noqa: E402

#: Two DISTINCT non-default numbers, so neither can be confused with the other
#: nor with anything the primitive would have supplied on its own.
_BUDGET = 4321.0
_GRACE = 1234.0


def test_the_probe_values_are_not_the_defaults():
    """THE GUARD ON THE GUARD. An assertion that happens to name a default
    passes whether or not the value was ever threaded — the #2097 trap."""
    for v in (_BUDGET, _GRACE):
        assert v != W.DEFAULT_STALL_GRACE_S
        assert v != W.DEFAULT_HARD_CEILING_S
    assert _BUDGET != _GRACE


class _Rec:
    """Capture what the supervisor was handed, and optionally fire the notice
    the way the real supervisor does at a crossing."""

    def __init__(self, cross_at=None):
        self.kw = None
        self.cmd = None
        self._cross_at = cross_at

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = list(cmd), kw
        if self._cross_at is not None and kw.get("ceiling_notice"):
            kw["ceiling_notice"](self._cross_at)
        return W.SupervisedResult(0, "ok", "", "natural", 0.0)


# ── 1. THE TWO NUMBERS ARE THREADED SEPARATELY ─────────────────────────────
def test_the_declared_budget_arrives_as_a_RECORDED_ceiling(monkeypatch,
                                                           tmp_path):
    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET))
    assert rec.kw["hard_ceiling_s"] == _BUDGET, (
        f"the declared budget did not reach the record: {rec.kw}")
    assert callable(rec.kw.get("ceiling_notice")), (
        "nothing announces the crossing, so the budget is recorded in a dict "
        "nobody reads rather than in the run's own transcript")


def test_the_budget_is_NOT_spent_as_the_stillness_window(monkeypatch,
                                                         tmp_path):
    """THE DEFECT ITSELF. With no grace declared the primitive's calibrated
    default must apply — the budget must not appear as the grace under any
    spelling."""
    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET))
    assert rec.kw.get("stall_grace_s", None) != _BUDGET, (
        "the wall BUDGET is still being spent as the stillness window — a "
        "runtime estimate answering a question about stillness")
    assert "stall_grace_s" not in rec.kw, (
        "an undeclared grace must be left to `_watchdog`'s calibrated "
        "default, not re-supplied from this file")


def test_a_caller_declared_grace_is_forwarded_and_stays_distinct(monkeypatch,
                                                                 tmp_path):
    """Both numbers at once, both non-default, both different: the only shape
    in which 'each is threaded' can be read off one call."""
    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET),
                       stall_grace_s=_GRACE)
    assert rec.kw["stall_grace_s"] == _GRACE
    assert rec.kw["hard_ceiling_s"] == _BUDGET
    assert rec.kw["stall_grace_s"] != rec.kw["hard_ceiling_s"]


def _pin_route(monkeypatch, *, container: bool) -> None:
    """Decide WHICH ROUTE `_run_in_docker` takes, instead of reading the host.

    `_run_in_docker` branches on `_container_exec.no_container_route()`, which
    is `shutil.which("docker") is None` — a fact about the machine the suite
    landed on, not about the code under test. Left unpinned, this file asserted
    the CONTAINER route's wiring on every host and the LOCAL route's reality on
    none: green beside a docker client, RED inside the EDA image and on the
    harness's `--no-engine` control arm, where the local kwargs carry
    `ceiling_notice` + `hard_ceiling_s` and no `kill` at all (vibe-ic#2145).
    Both routes exist and both are asserted, each in its own arm.
    """
    if container:
        try:
            F.docker_image()
        except _eda_pin.ImageNotResolvable as exc:
            pytest.skip(f"NOT_MEASURED: container launch image unavailable: {exc}")
    monkeypatch.setattr(TDF._CE, "no_container_route",
                        lambda: container is False)


def test_the_container_route_wires_the_reap_and_the_container_probe(
        monkeypatch, tmp_path):
    """THE OTHER DIRECTION. Separating the two numbers must not cost the pair
    that makes an ephemeral `docker run` supervisable at all: the CPU probe
    that reads the CONTAINER's /proc, and the reap that kills by the identity
    this call minted.

    Both belong HERE and only here: the supervisor's own defaults read the
    `docker run` CLIENT's /proc and kill the CLIENT's process group, and the
    engine is in neither.

    The pair is checked by IDENTITY, not by `callable`. A reap built for some
    other name satisfies `callable` and still leaves the orphan burning a core,
    so the factories are recorded and the objects handed to the supervisor must
    be the ones built for the name that is actually on the argv."""
    _pin_route(monkeypatch, container=True)
    built = {}
    # The recorders DELEGATE to the real factories, captured before the patch,
    # so what reaches the supervisor is the genuine reap and probe — a stub
    # would make `callable` true and prove nothing.
    real_reap = TDF._dwd.ephemeral_container_reap
    real_probe = TDF._dwd.ephemeral_container_cpu_probe

    def _reap_factory(name, *a, **kw):
        built["reap_name"] = name
        built["reap"] = real_reap(name, *a, **kw)
        return built["reap"]

    def _probe_factory(name, *a, **kw):
        built["probe_name"] = name
        built["probe"] = real_probe(name, *a, **kw)
        return built["probe"]

    monkeypatch.setattr(TDF._dwd, "ephemeral_container_reap", _reap_factory)
    monkeypatch.setattr(TDF._dwd, "ephemeral_container_cpu_probe",
                        _probe_factory)

    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET))

    assert rec.cmd[:2] == ["docker", "run"], rec.cmd
    name = [rec.cmd[i + 1] for i, a in enumerate(rec.cmd) if a == "--name"]
    assert len(name) == 1 and name[0].startswith("vibeic_tdf_"), rec.cmd
    assert callable(rec.kw.get("kill"))
    assert callable(rec.kw.get("cpu_probe"))
    assert built.get("reap_name") == name[0], (
        f"the reap was built for {built.get('reap_name')!r} but the argv names "
        f"{name[0]!r} — it would reap nothing")
    assert built.get("probe_name") == name[0], (
        f"the CPU probe was built for {built.get('probe_name')!r} but the argv "
        f"names {name[0]!r} — it would read nothing")
    assert rec.kw["kill"] is built["reap"]
    assert rec.kw["cpu_probe"] is built["probe"]


def test_the_local_route_leaves_the_reap_to_the_host_supervisor(
        monkeypatch, tmp_path):
    """THE ROUTE THE IMAGE ACTUALLY TAKES, asserted rather than assumed.

    In local mode the engine IS a descendant of this process, so the reaper
    that supervises it is the seam's OWN. Passing the ephemeral pair here would
    address a container that was never created — a probe that always reads None
    and a reap that always finds nothing, i.e. supervision that cannot fire.

    That the inherited pair is REAL is the sibling test below; without it
    "passes nothing" would be indistinguishable from "is not supervised"."""
    _pin_route(monkeypatch, container=False)
    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET))

    assert rec.cmd[:2] == ["bash", "-c"], rec.cmd
    assert "--name" not in rec.cmd and "docker" not in rec.cmd, rec.cmd
    assert "kill" not in rec.kw, (
        "the local route passed a kill of its own; the only one it could pass "
        "is the ephemeral container reap, which would address a container that "
        "was never created")
    assert "cpu_probe" not in rec.kw, (
        "the local route passed a cpu_probe of its own; the container probe "
        "would read a container that was never created")
    # the shared supervision contract is threaded on THIS route too
    assert rec.kw["hard_ceiling_s"] == _BUDGET
    assert callable(rec.kw.get("ceiling_notice"))


def test_the_reaper_the_local_route_inherits_is_real(monkeypatch):
    """The seam supplies what the local route declines to.

    `run_host_supervised` injects `host_cpu_probe` when the caller names none —
    asserted here by driving the REAL seam, which is why this is a separate
    test: the arm above replaces `run_host_supervised` with a recorder, so it
    cannot also measure what that function does.

    The KILL half is `run_supervised`'s `kill = kill or _default_kill`, and that
    `_default_kill` signals the whole process GROUP (rather than only the head
    of the tree) is proven against a real `sh -> sleep` pair in
    `test_a_stall_reaps_the_whole_process_group.py`. It is cited, not restated:
    a second copy of that assertion would drift from the one that drives a real
    process."""
    seen = {}
    monkeypatch.setattr(
        W, "run_supervised",
        lambda cmd, **kw: (seen.update(kw),
                           W.SupervisedResult(0, "ok", "", "natural", 0.0))[1])
    W.run_host_supervised(["bash", "-c", "true"])
    assert seen.get("cpu_probe") is W.host_cpu_probe, seen
    assert callable(W._default_kill)


# ── 2. THE CROSSING IS ANNOUNCED, AND THE JOB IS NOT STOPPED ───────────────
def test_a_crossing_is_announced_once_and_the_job_runs_on(monkeypatch,
                                                          tmp_path, capsys):
    rec = _Rec(cross_at=9999.0)
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    ec, out, _err = TDF._run_in_docker(tmp_path, "yosys /work/b.ys",
                                       timeout=int(_BUDGET))
    assert ec == 0 and out == "ok", (
        "the crossing changed the outcome — a recorded budget that terminates "
        "is a wall with a nicer name")
    said = capsys.readouterr().out
    assert "RECORDED CEILING CROSSED" in said, said
    assert "9999.0" in said, said
    assert str(int(_BUDGET)) in said, (
        f"the announcement does not name the budget that was crossed: {said}")


# ── 3. THE CALLER THREADS THE SIZE-SCALED WALL, NOT A CONSTANT ─────────────
def _batch_launch_call() -> ast.Call:
    """The `_run_in_docker` call inside `_run_batch`, located by its ENCLOSING
    FUNCTION rather than by line number or by the shape of an argument — there
    are three f-string launches in this file and only one of them is the batch.
    """
    tree = ast.parse((_PROGRAMS / "transition_fault_atpg_run.py").read_text())
    batches = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_run_batch"]
    assert len(batches) == 1, f"expected one `_run_batch`, found {len(batches)}"
    found = [n for n in ast.walk(batches[0])
             if isinstance(n, ast.Call)
             and (n.func.id if isinstance(n.func, ast.Name)
                  else getattr(n.func, "attr", "")) == "_run_in_docker"]
    assert len(found) == 1, f"expected one batch launch, found {len(found)}"
    return found[0]


def test_the_batch_still_declares_the_size_scaled_wall_as_its_budget():
    """The number itself is untouched by this change — it is what the number
    DOES that moved. A fix that quietly dropped the size scaling would pass
    every assertion above."""
    kw = {k.arg: k for k in _batch_launch_call().keywords}
    assert "timeout" in kw, "the batch stopped declaring a budget at all"
    assert ast.unparse(kw["timeout"].value) == "max(30, int(wall))", (
        f"the batch's declared budget is no longer the size-scaled wall: "
        f"{ast.unparse(kw['timeout'].value)}")


def test_the_scaled_wall_is_above_the_floor_for_a_real_flop_count():
    """`_scaled_wall_budget` is the source of the number the ceiling now
    records; if it collapsed to the floor the record would be a constant."""
    assert TDF._scaled_wall_budget(1800, 0) == 1800
    assert TDF._scaled_wall_budget(1800, 2922) > 1800


# ── 4. THE SUPERVISION CONTRACT IS THE SIBLING'S, NOT A SECOND COPY ────────
def test_the_kwargs_come_from_the_shared_builder_not_a_local_spelling():
    """Two spellings of one supervision contract is how the two DFT producers
    drift apart — the reason the CPU probe and the reap are imported here and
    not copied. MEMBERSHIP, not text: the keys the shared builder produces are
    exactly the supervision keys this launch hands over."""
    built = F._atpg_supervision_kw(_BUDGET, lambda _e: None, _GRACE)
    assert set(built) == {"hard_ceiling_s", "ceiling_notice", "stall_grace_s"}
    assert F._atpg_supervision_kw(_BUDGET, lambda _e: None, None).keys() \
        == {"hard_ceiling_s", "ceiling_notice"}, (
        "an unset grace must not be materialised as a keyword")


# ── 5. THE MUTATION ARM: revert the fix line, require the finding ───────────
# The pristine-file arm (recorded in the lane's LAND.md: 4 of these 9 red
# against base 94617408759e) proves the file reproduces. This one rides IN the
# suite, so a future edit that quietly puts the budget back into the grace is
# caught by a test rather than by someone remembering to re-measure.
_FIXED_LAUNCH = """    res = _wd.run_host_supervised(
        docker_cmd,
        kill=_dwd.ephemeral_container_reap(cname),
        cpu_probe=_dwd.ephemeral_container_cpu_probe(cname),
        **_far._atpg_supervision_kw(float(timeout), _ceiling_notice,
                                    stall_grace_s))
"""
_PRE_FIX_LAUNCH = """    res = _wd.run_host_supervised(
        docker_cmd, stall_grace_s=float(timeout),
        kill=_dwd.ephemeral_container_reap(cname),
        cpu_probe=_dwd.ephemeral_container_cpu_probe(cname))
"""


def _launch_kwargs(src: str) -> list:
    """The keyword NAMES **every** `run_host_supervised` call in
    `_run_in_docker` hands over — one set per launch, read off `src` by AST. A
    `**splat` is reported as the literal token `**` so the two shapes are
    distinguishable: the fix passes its ceiling through one, and a test that
    could not see that would be blind to the very thing it checks.

    EVERY LAUNCH, NOT THE LAUNCH. This helper asserted `len(calls) == 1` until
    vibe-ic#2063 RB2-07 (v1.18.84) added a SECOND supervised surface to this
    function — the local route taken when there is no docker client, i.e. the
    only route an in-image run has. It arrived carrying
    `stall_grace_s=float(timeout)`, the exact shape O2 removes, and a
    single-call locator would have gone red for the wrong reason ("got 2")
    while the defect it names shipped on the surface that matters most.
    A contract that holds on one branch of a function is not a contract."""
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_run_in_docker"]
    assert len(fns) == 1, f"expected one `_run_in_docker`, found {len(fns)}"
    calls = [n for n in ast.walk(fns[0])
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "run_host_supervised"]
    assert calls, "no supervised launch found — the locator is measuring nothing"
    return [{(k.arg if k.arg is not None else "**") for k in c.keywords}
            for c in calls]


def _container_launch(src: str) -> set:
    """The CONTAINER route's kwargs, selected by its own content rather than by
    position: it is the launch that carries the ephemeral-container `kill` and
    `cpu_probe`, which the local route by construction does not.

    NOT `[-1]`: `ast.walk` is breadth-first, so "the last call found" is not
    "the last call in the file", and an index would silently start judging the
    other surface the next time this function is edited."""
    sets = [kw for kw in _launch_kwargs(src) if "kill" in kw]
    assert len(sets) == 1, f"expected one container launch, got {len(sets)}"
    return sets[0]


def test_EVERY_shipped_launch_refuses_to_spell_the_budget_as_the_grace():
    """Both surfaces of `_run_in_docker` — the container route and the local
    route vibe-ic#2063 added — carry the same contract, or the producer ships
    the fix only where a docker client happens to exist."""
    src = (_PROGRAMS / "transition_fault_atpg_run.py").read_text()
    assert _FIXED_LAUNCH in src, (
        "the launch no longer matches the shape this control mutates — update "
        "the control rather than deleting it")
    launches = _launch_kwargs(src)
    assert len(launches) >= 2, (
        f"expected the container route AND the local route, saw "
        f"{len(launches)} supervised launch(es)")
    for i, kw in enumerate(launches):
        assert "stall_grace_s" not in kw, (
            f"supervised launch #{i} spells `stall_grace_s=` at the call site; "
            f"the grace is threaded through the shared builder, and a literal "
            f"here is how the budget got spent as the grace in the first place")
        assert "**" in kw, (
            f"supervised launch #{i} no longer builds its kwargs with the "
            f"shared `_atpg_supervision_kw`, so the surfaces can drift apart")


def test_the_LOCAL_route_carries_the_contract_too(monkeypatch, tmp_path):
    """EXECUTED on the route an IN-IMAGE run actually takes. vibe-ic#2063 exists
    because with no docker client this producer graded nothing; the fix for that
    must not re-introduce the budget-as-grace it was landed beside."""
    rec = _Rec()
    monkeypatch.setattr(TDF._wd, "run_host_supervised", rec)
    monkeypatch.setattr(TDF._CE, "no_container_route", lambda: True)
    monkeypatch.setattr(TDF._CE, "localise_mounted_paths",
                        lambda cmd, _m: cmd)
    monkeypatch.setattr(TDF, "_announce_local_tdf_route", lambda *_a: None)
    TDF._run_in_docker(tmp_path, "yosys /work/b.ys", timeout=int(_BUDGET))
    assert rec.kw["hard_ceiling_s"] == _BUDGET, (
        f"the local route records no ceiling: {rec.kw}")
    assert rec.kw.get("stall_grace_s", None) != _BUDGET, (
        "the local route still spends the budget as the stillness window")
    assert callable(rec.kw.get("ceiling_notice"))
    assert rec.cmd[0] == "bash", rec.cmd


def test_putting_the_budget_back_into_the_grace_is_CAUGHT():
    """THE CONTROL. Revert exactly the fix line and require the finding."""
    src = (_PROGRAMS / "transition_fault_atpg_run.py").read_text()
    mutated = src.replace(_FIXED_LAUNCH, _PRE_FIX_LAUNCH, 1)
    assert mutated != src, "the mutation did not apply — update this control"
    container = _container_launch(mutated)
    assert "stall_grace_s" in container, (
        "the mutated tree does not show the defect this test claims to detect")
    assert "hard_ceiling_s" not in container and "**" not in container, (
        "the mutated tree still records a ceiling, so reverting the line would "
        "not be caught by the assertions above")


def test_the_pre_fix_launch_recorded_no_ceiling_at_all():
    """WHY THE MUTATION IS THE DEFECT AND NOT MERELY A DIFFERENT SPELLING: the
    pre-fix call passes no ceiling under any name, so the size-scaled budget
    the run was planned against reached no record anywhere."""
    kw = _container_launch((_PROGRAMS / "transition_fault_atpg_run.py")
                           .read_text().replace(_FIXED_LAUNCH,
                                                _PRE_FIX_LAUNCH, 1))
    assert kw == {"stall_grace_s", "kill", "cpu_probe"}, kw
