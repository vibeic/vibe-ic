"""A session that can only ask about ONE cell must not probe all 63 steps.

vibe-ic#1412. `test_matrix_d6_skip_discipline.probe_for` used to be

    return _all_probes()[F.normalize_id(step_id)]

and `_all_probes` builds a `Probe` for every one of the flow's 63 steps: 3-5
synthetic projects each, every one of them a `flow_compliance_check`
SUBPROCESS bounded at `_SUBPROCESS_TIMEOUT_S = 60`, fanned out 8 threads wide.

That is the right shape for the module's whole-sweep tests, which read all 63.
It is the wrong shape for the 63 parametrised cells, each of which reads ONE,
and it is the mutation ledger's LOCK 2 that pays for it. LOCK 2 replays every
(entry, step) pair by running the single cell nodeid as its own pytest
process, twice (baseline and mutant), eight pairs at a time
(`matrix_mutation_ledger.replay_many(..., jobs=8)`). Every one of those
processes built all 63 probes, so the ledger asked the host for on the order of
8 x 8 concurrent gate subprocesses to measure eight cells.

THE CONSEQUENCE IS A WRONG ANSWER, NOT A SLOW ONE. Under that self-inflicted
load the 60 s bound fires, the uncaught `TimeoutExpired` fails the cell, and
`_cell_rc_from_report` reads the cell's report as `rc=1`. The ledger then
records `baseline_rc=1` -> `ALREADY_RED` -> "the witness was RED BEFORE its
mutation was applied" — a statement about the gate that nothing measured. On
this tree, at load average 238 on 32 cores, both witnesses the issue names PASS
when they are given room:

    test_d6_skip_discipline[step21] + [stepP0]   2 passed in 121.21s
    matrix_mutation_ledger.py --replay D6-UMBRELLA-ALWAYS-SKIPS --jobs 1
                                                 REDDENED (137.3s)

WHY THESE ASSERTIONS AND NOT A STOPWATCH
----------------------------------------
Same reason `test_d7_single_tree_lookup_is_lazy.py` gives, and it is measured
on this fleet rather than assumed: these hosts run heavily oversubscribed (load
average 238 on 32 cores while this was written, 64 concurrent `pytest`
processes belonging to other agents), and two readings of the same sweep differ
several-fold from contention alone. A "finishes within N seconds" assertion
would bake that contention into a constant and flap on exactly the busy hosts
this defect appears on.

So what is pinned here is STRUCTURAL and host-independent: HOW MANY STEPS GET
PROBED, counted — never how long it took.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import flow_matrix.flowref as F
import test_matrix_d6_skip_discipline as D6

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: A pytest plugin that replaces `_probe_step` with a counter and writes the
#: step ids it was asked for. Installed with `-p`, so it is loaded before any
#: test runs; the patching is deferred to `pytest_collection_modifyitems`
#: because `-p` plugins load BEFORE the conftest that puts `programs/tests` on
#: the path — and because the module only exists to patch once collection has
#: imported it.
#:
#: IT PATCHES EVERY COPY IN ``sys.modules``, NOT ``import <name>``. `pytest.ini`
#: sets ``--import-mode=importlib``, so the collected module is registered as
#: ``programs.tests.test_matrix_d6_skip_discipline`` while a plain
#: ``import test_matrix_d6_skip_discipline`` builds a SECOND, unrelated module
#: object. Patching that second one counted 0 probes and would have read as
#: "the fix works" for the exact reason it proves nothing.
_COUNTER_PLUGIN = '''\
import os
import pathlib
import sys

_SEEN = []


def _d6_modules():
    return [m for name, m in list(sys.modules.items())
            if m is not None
            and name.rsplit(".", 1)[-1] == "test_matrix_d6_skip_discipline"]


def pytest_collection_modifyitems(session, config, items):
    for mod in _d6_modules():
        def _stub(step_id, _mod=mod):
            _SEEN.append(str(step_id))
            return _mod.Probe(step_id=step_id)

        mod._probe_step = _stub


def pytest_sessionfinish(session, exitstatus):
    lines = ["#modules=%d" % len(_d6_modules())] + _SEEN
    pathlib.Path(os.environ["D6_PROBE_LOG"]).write_text(
        "\\n".join(lines), encoding="utf-8")
'''


class _FakeCell:
    """Stands in for a `flow_matrix.cells.Cell` in a callspec."""

    def __init__(self, step_id: str) -> None:
        self.step_id = step_id


class _FakeCallSpec:
    def __init__(self, params: Dict[str, Any]) -> None:
        self.params = params


class _FakeItem:
    """A collected pytest item, with or without a `cell` parametrisation."""

    def __init__(self, cell_step: Optional[str] = None) -> None:
        if cell_step is not None:
            self.callspec = _FakeCallSpec({"cell": _FakeCell(cell_step)})


def _counting_probe_step(seen: List[str]):
    def _stub(step_id):
        seen.append(str(step_id))
        return D6.Probe(step_id=step_id)

    return _stub


def _isolated(monkeypatch, budget: Optional[Tuple[str, ...]]) -> List[str]:
    """Fresh probe cache + a recorded budget; returns the call log to read."""
    seen: List[str] = []
    monkeypatch.setattr(D6, "_PROBE_CACHE", {})
    monkeypatch.setattr(D6, "_PROBE_BUDGET", budget)
    monkeypatch.setattr(D6, "_probe_step", _counting_probe_step(seen))
    return seen


def test_the_population_is_not_empty():
    """A count-based guard over an empty population proves nothing."""
    steps = list(F.step_ids())
    assert len(steps) > 50, (
        f"the flow declares {len(steps)} steps; every assertion below counts "
        f"probes against that population and would pass vacuously over a "
        f"short one")


def test_a_single_cell_session_probes_only_that_cells_step(monkeypatch):
    """THE FIX. One selected cell -> one probe, not 63."""
    seen = _isolated(monkeypatch, ("21",))
    D6.probe_for("21")
    assert seen == ["21"], (
        f"a session whose only collected item is the step-21 cell probed "
        f"{len(seen)} step(s): {seen}. Each probe is 3-5 "
        f"flow_compliance_check subprocesses under a "
        f"{D6._SUBPROCESS_TIMEOUT_S}s "
        f"bound, and the mutation ledger runs this nodeid 8 processes at a "
        f"time — probing the other 62 is what makes the bound fire and the "
        f"ledger call a green witness ALREADY_RED (vibe-ic#1412).")


def test_the_counter_still_sees_all_63_so_the_guard_above_is_not_blind(
        monkeypatch):
    """CONTROL. The same instrument, on the whole-sweep path, must count 63.

    Without this, `seen == ["21"]` above would also pass if `_build_probes`
    had simply stopped probing anything at all.
    """
    seen = _isolated(monkeypatch, None)
    probes = D6._all_probes()
    assert sorted(seen) == sorted(str(s) for s in F.step_ids()), (
        f"the whole-sweep path probed {len(seen)} step(s), not "
        f"{len(list(F.step_ids()))}")
    assert len(probes) == len(list(F.step_ids()))


def test_a_whole_suite_session_still_probes_every_step(monkeypatch):
    """The sweep tests must keep seeing all 63 through `probe_for` itself.

    `_PROBE_BUDGET is None` is what every whole-file and whole-suite run gets,
    and four tests in the module loop `probe_for` over `F.step_ids()`. This is
    the leg that keeps the fix from narrowing what THEY measure.
    """
    seen = _isolated(monkeypatch, None)
    D6.probe_for("21")
    assert sorted(seen) == sorted(str(s) for s in F.step_ids()), (
        f"a session that can ask about any step probed {len(seen)}; the "
        f"whole-flow behaviour must be unchanged when the budget is unknown")


def test_the_budget_is_read_off_pytest_collection_not_guessed():
    """Per-cell items contribute their own step; anything else means ALL."""
    assert D6._budget_from(
        [_FakeItem("21"), _FakeItem("P0"), _FakeItem("21")]) == ("21", "P0")
    assert D6._budget_from([_FakeItem("21"), _FakeItem()]) is None, (
        "one selected item that is not a per-cell parametrisation is assumed "
        "to sweep, and the budget must widen to every step — narrowing it "
        "would silently starve a whole-sweep test's measurement")
    assert D6._budget_from([_FakeItem()]) is None


def test_a_step_outside_the_budget_is_probed_rather_than_missing(monkeypatch):
    """A caller the fixture did not anticipate gets a probe, never a KeyError.

    Slower, never wrong: the fallback is the whole point of recording a budget
    rather than a hard-coded selection.
    """
    seen = _isolated(monkeypatch, ("21",))
    probe = D6.probe_for("22")
    assert F.normalize_id(probe.step_id) == F.normalize_id("22")
    assert "22" in seen


def test_the_probe_a_cell_gets_is_the_one_probe_step_built(monkeypatch):
    """No transformation on either path — the same object, cached once.

    The equivalence that matters for a mutation replay: the cell measured by a
    single-nodeid session must be the cell a full session would have measured.
    `_probe_step` is untouched by this change, so it is enough to pin that both
    paths hand back exactly what it returned, and that a second ask re-uses it.
    """
    seen = _isolated(monkeypatch, ("21",))
    first = D6.probe_for("21")
    again = D6.probe_for("21")
    assert first is again, "the per-step cache is not caching"
    assert seen == ["21"], f"probe_for re-probed on a cache hit: {seen}"
    assert F.normalize_id(first.step_id) == F.normalize_id("21")
    assert D6._PROBE_CACHE[F.normalize_id("21")] is first


def _probes_a_real_session_builds(tmp_path, *nodeids: str) -> List[str]:
    """Run a REAL pytest on these nodeids; return the step ids it probed.

    `_probe_step` is replaced by a counter, so the cells fail for want of a
    measurement and the exit status is meaningless. The COUNT is the subject.
    """
    plugin_dir = tmp_path / "plug"
    plugin_dir.mkdir()
    (plugin_dir / "d6_probe_counter.py").write_text(
        _COUNTER_PLUGIN, encoding="utf-8")
    log = tmp_path / "probed.txt"
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["D6_PROBE_LOG"] = str(log)
    env["PYTHONPATH"] = (str(plugin_dir) + os.pathsep
                         + env.get("PYTHONPATH", ""))
    proc = _pr.run(
        [sys.executable, "-m", "pytest", *nodeids, "-q", "--no-header",
         "-p", "no:randomly", "-p", "no:cacheprovider",
         "-p", "d6_probe_counter"],
        cwd=str(F.PLUGIN_ROOT), capture_output=True, text=True,
        env=env)
    assert log.is_file(), (
        f"the counter plugin never wrote its log, so this measured NOTHING — "
        f"an absent file is not a count of zero probes. rc={proc.returncode}\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]
    header, seen = lines[0], lines[1:]
    assert header == "#modules=1", (
        f"the counter patched {header!r} copies of the d6 module. It must be "
        f"exactly one: zero means it instrumented nothing and every count "
        f"below would be a false 'the fix works', and more than one means the "
        f"session is running two module objects and the count is ambiguous.\n"
        f"rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return seen


def test_the_budget_fixture_narrows_a_REAL_single_nodeid_session(tmp_path):
    """END TO END. Every other test here sets the budget by hand.

    This one does not: it starts a real pytest on the exact nodeid shape
    `matrix_mutation_ledger.cell_nodeid(6, "21")` builds, lets the
    session-scoped fixture read the real `session.items`, and reads back which
    steps were probed. It is the leg that proves the FIXTURE is wired — that
    pytest items really carry `callspec.params["cell"]`, and that the fixture
    runs before the first cell asks for a probe.
    """
    probed = _probes_a_real_session_builds(
        tmp_path,
        "programs/tests/test_matrix_d6_skip_discipline.py"
        "::test_d6_skip_discipline[step21]")
    assert probed == ["21"], (
        f"a real single-nodeid session probed {len(probed)} step(s): {probed}. "
        f"That is the shape the mutation ledger runs 8 at a time, twice per "
        f"pair (vibe-ic#1412).")


def test_two_selected_cells_probe_exactly_those_two(tmp_path):
    """CONTROL. The narrowing follows the SELECTION, not a hard-coded one.

    A budget that always answered "one step" would pass the test above and
    starve every other cell in a two-cell session.
    """
    base = "programs/tests/test_matrix_d6_skip_discipline.py::test_d6_skip_discipline"
    probed = _probes_a_real_session_builds(
        tmp_path, f"{base}[step21]", f"{base}[stepP0]")
    assert sorted(probed) == ["21", "P0"], (
        f"a two-cell session probed {sorted(probed)}")
