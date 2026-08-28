"""The dependency dimension, recomputed rather than assessed.

Synthetic flows — the rule is about graph shape, not about any real step.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GATE = Path(__file__).resolve().parent.parent / "flow_dependency_graph_check.py"
yaml = pytest.importorskip("yaml")

# Read the entry points OUT OF THE PROGRAM rather than re-typing them here.
# vibe-ic#923 removed P0 from this set (it gained the ordering edge its own
# required_inputs had always implied) and three fixtures below, each carrying a
# hand-typed copy, went stale in the same commit. A fixture derived from the
# program cannot go stale without the program changing.
_ROOTS = sorted(
    importlib.import_module("flow_dependency_graph_check").DECLARED_ROOTS)


def _run(flow: Path):
    p = _pr.run([sys.executable, str(GATE), "--flow", str(flow)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _flow(tmp: Path, steps) -> Path:
    f = tmp / "flow.yaml"
    f.write_text(yaml.safe_dump({"steps": steps}, allow_unicode=True),
                 encoding="utf-8")
    return f


def _s(sid, deps=None):
    d = {"id": sid, "name": f"step {sid}"}
    if deps is not None:
        d["blocks_on"] = deps
    return d


def test_the_real_flow_is_sound():
    """The shipped flow: no dangling reference, no cycle, roots as declared."""
    rc, out = _run(GATE.parent.parent / "flow" / "phase1_phase2_phase3.yaml")
    assert rc == 0, out
    assert "0 dangling reference(s), 0 cycle(s)" in out


def test_a_dangling_reference_fails(tmp_path):
    """A reference to a step that does not exist blocks on nothing, and the
    ordering guard reading this graph skips it silently."""
    rc, out = _run(_flow(tmp_path, [_s("D1"), _s(9, [404])]))
    assert rc == 1, out
    assert "does not declare" in out


def test_a_cycle_fails(tmp_path):
    rc, out = _run(_flow(tmp_path, [_s("D1"), _s(2, [3]), _s(3, [2])]))
    assert rc == 1, out
    assert "cycle" in out


def test_a_self_loop_is_a_cycle(tmp_path):
    rc, out = _run(_flow(tmp_path, [_s("D1"), _s(2, [2])]))
    assert rc == 1, out
    assert "cycle" in out


def test_a_new_root_fails(tmp_path):
    """A step with no dependencies that nobody declared as an entry point is a
    step that fell off the chain until someone says otherwise."""
    rc, out = _run(_flow(tmp_path, [_s("D1"), _s(7)]))
    assert rc == 1, out
    assert "fell off the chain" in out


def test_a_declared_root_that_gained_dependencies_forces_the_list_to_shrink(tmp_path):
    """The half people forget — and the half that caught a stale-tree baseline
    on this check's first real run.

    Constructed from ONE declared root plus a synthetic ordinary step, rather
    than from two declared roots. The old form asserted `len(_ROOTS) >= 2` as
    an explicit premise, and vibe-ic#1070 retired that premise by removing A1
    from the register — A1 was baselined as an entry point while its own
    `required_inputs` declared two reads from D1, so declaring that edge
    required the register to shrink to `{"D1"}`.

    The assertion is unchanged (rc 1, "must shrink"); only the fixture is, and
    it is now more general: it holds for any register with at least one root
    instead of at least two, so the next legitimate shrink cannot break it
    again for a reason that has nothing to do with what it measures.
    """
    assert _ROOTS, f"premise: need at least one declared root, got {_ROOTS}"
    root = _ROOTS[0]
    #: `999` is an ordinary step, deliberately NOT in the register — the
    #: subject is a DECLARED root that acquired a dependency, so the thing it
    #: depends on must not itself be a declared root.
    steps = [_s(root, [999]), _s(999)]
    rc, out = _run(_flow(tmp_path, steps))
    assert rc == 1, out
    assert "must shrink" in out


def test_the_declared_roots_alone_pass(tmp_path):
    rc, out = _run(_flow(tmp_path, [_s(r) for r in _ROOTS]))
    assert rc == 0, out


def test_a_dangling_edge_is_not_reported_as_a_cycle(tmp_path):
    """Dangling edges are excluded from the graph so cycle detection reports
    cycles and not the consequences of a separate defect."""
    rc, out = _run(_flow(tmp_path, [_s(r) for r in _ROOTS] + [_s(5, [404])]))
    assert rc == 1, out
    assert "cycle" not in out


def test_stage_containers_are_not_steps(tmp_path):
    rc, out = _run(_flow(tmp_path, [_s(r) for r in _ROOTS]
                                   + [{"id": "stage_2", "name": "Stage 2"}]))
    assert rc == 0, out


def test_an_empty_flow_is_not_checked(tmp_path):
    f = tmp_path / "e.yaml"
    f.write_text("steps: []\n", encoding="utf-8")
    rc, out = _run(f)
    assert rc == 2, out
    assert "NOT CHECKED" in out
