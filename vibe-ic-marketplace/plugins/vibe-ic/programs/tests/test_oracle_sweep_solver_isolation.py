"""The solver must not be able to reach the golden-reading sweep.

`programs/oracle_self_consistency_sweep.py` READS GOLDEN. That is legitimate
exactly once — as a harness-side audit OF THE DATASET — and it is illegitimate
everywhere else. §4.05 says a solve reads the design INPUT and nothing else, so
the boundary has to be a MECHANISM, not a promise in a docstring: the bvev2
leak happened because an artefact justified by oracle-FAIL observations reached
the solving side.

Two mechanisms, and this file holds both.

  1. REACHABILITY. Walk the import graph and the subprocess argv literals out
     of the solve entry points (`benchmark_dispatch.py`, which carries the
     `--solve` verb, and `vibe_ic_one_shot_runner.py`, the runner it drives).
     The sweep and its adapters must not appear anywhere in the closure.

  2. REFUSAL. Even if a person runs it by hand, the sweep refuses to write
     inside a solve run directory, so golden-derived bytes cannot land where a
     solver reads.

Both directions are proven. The walk is validated on a CONTROL module that IS
reachable from the same entry points by the same rules — without that, an
absent result would be indistinguishable from a walk that finds nothing.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))

SOLVE_ENTRY_POINTS = ("benchmark_dispatch.py", "vibe_ic_one_shot_runner.py")

# What must stay out of reach.
FORBIDDEN = ("oracle_self_consistency_sweep",
             "verilogeval_oracle_adapter",
             "rtllm_oracle_adapter")

# The control: a module the same walk MUST find, or the walk proves nothing.
# `_designs_root` is imported by the scorer the dispatcher runs; `score_one`
# and `task_nature_route` are named as argv literals. Any one of them arriving
# is enough to show both edge kinds are being followed.
CONTROL_ANY = ("task_nature_route", "_designs_root", "score_one",
               "benchmark_clean_room_check", "vibe_ic_entry_guard")


def _module_edges(path: Path) -> set[str]:
    """Every plugin module `path` could reach: imports plus the `*.py` argv
    literals it hands to a subprocess. Names only — no resolution of dynamic
    dispatch, which is why the CONTROL assertion below is mandatory."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.endswith(".py"):
                out.add(Path(v).stem)
    return out


def _reachable() -> set[str]:
    seen: set[str] = set()
    queue = [e for e in SOLVE_ENTRY_POINTS if (PROGRAMS / e).is_file()]
    assert queue, f"no solve entry point found under {PROGRAMS}"
    frontier = [PROGRAMS / q for q in queue]
    while frontier:
        cur = frontier.pop()
        for name in _module_edges(cur):
            if name in seen:
                continue
            seen.add(name)
            nxt = PROGRAMS / f"{name}.py"
            if nxt.is_file():
                frontier.append(nxt)
    return seen


@pytest.fixture(scope="module")
def closure():
    return _reachable()


def test_the_walk_actually_walks(closure):
    """The negative control. If this fails, every assertion below is vacuous."""
    hit = sorted(c for c in CONTROL_ANY if c in closure)
    assert hit, (
        "the solve-entry closure reached none of "
        f"{CONTROL_ANY}, so it is not following the plugin's own edges and "
        "the isolation assertions below would pass on an empty set")
    assert len(closure) > 20, f"closure is implausibly small: {len(closure)}"


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_the_solve_path_cannot_reach_the_golden_reading_sweep(forbidden, closure):
    assert forbidden not in closure, (
        f"{forbidden} is reachable from the solve entry points "
        f"{SOLVE_ENTRY_POINTS}. That module READS GOLDEN; a solver that can "
        "import or invoke it can read the answer. Keep the sweep on the "
        "harness side.")


def test_the_sweep_itself_names_nothing_that_solves():
    """The other direction of the same boundary: the audit must not call into
    the solving machinery either, or a future edit could make the graph above
    true in reverse."""
    edges = _module_edges(PROGRAMS / "oracle_self_consistency_sweep.py")
    for solver in ("vibe_ic_one_shot_runner", "benchmark_dispatch",
                   "task_nature_route", "design_one_shot_runner"):
        assert solver not in edges, (
            f"the sweep reaches {solver}: an audit that can start a solve is "
            "no longer an audit")


def test_the_sweep_refuses_to_write_inside_a_solve_run(tmp_path):
    import oracle_self_consistency_sweep as S
    run = tmp_path / "run"
    (run / "deep" / "deeper").mkdir(parents=True)
    (run / ".bench_config.json").write_text("{}")
    ds = tmp_path / "ds"
    ds.mkdir()
    assert S.refuse_reason(run / "deep" / "deeper", ds), \
        "a golden-reading audit must refuse to write inside a solve run"
    # …and the refusal is not a blanket one: an ordinary path is allowed.
    assert S.refuse_reason(tmp_path / "audit_out", ds) is None
    # A dataset argument that is itself a run directory is refused too.
    (ds / ".bench_config.json").write_text("{}")
    assert S.refuse_reason(tmp_path / "audit_out", ds)
