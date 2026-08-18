#!/usr/bin/env python3
"""ORGANIC #403 — a generator must not silently replace the design's own RTL.

`_try_deterministic_rtl_dispatch` is the FIRST thing `step_rtl_gen` does and
it wrote `phase2/stage1/rtl/<module>.sv` unconditionally.
`consume_reused_ip_rtl`, which stages the design's shipped implementation,
runs AFTER it and stages only into an EMPTY tree — so by the time it looked,
the generator owned the directory and it skipped. The one guard that existed
covered `input/vendor_rtl/` alone and sat past the write.

Both directions are tested. "Never generates" would pass the headline case
and break the feature, so the paired cases assert that a project with a spec
and NO shipped RTL still generates, and that a testbench-only tree is not
mistaken for an implementation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import design_one_shot_runner as D  # noqa: E402
import reused_ip_rtl_consume as R  # noqa: E402

# The fixture the issue cites — tests/test_truth_table_rtl_gen.py PROB069.
# An invented spec of my own did NOT dispatch, and reading that as "cannot
# reproduce" would have dismissed a real defect: the fixture has to be shaped
# like the thing it stands for.
SPEC = {
    "kind": "truth_table", "module": "TopModule",
    "inputs": [{"name": "x3"}, {"name": "x2"}, {"name": "x1"}],
    "outputs": [{"name": "f"}],
    "rows": [{"in": "000", "out": "0"}, {"in": "001", "out": "0"},
             {"in": "010", "out": "1"}, {"in": "011", "out": "1"},
             {"in": "100", "out": "0"}, {"in": "101", "out": "1"},
             {"in": "110", "out": "0"}, {"in": "111", "out": "1"}],
    "default": "0",
}
OWN_RTL = ("module TopModule(input x3, x2, x1, output f);\n"
           "  assign f = x1;  // the design's own implementation\n"
           "endmodule\n")


def _project(tmp_path: Path, own_rtl_rel: str = None) -> Path:
    (tmp_path / "phase2/stage1").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase2/stage1/rtl_spec.json").write_text(json.dumps(SPEC))
    if own_rtl_rel:
        d = tmp_path / own_rtl_rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "TopModule.v").write_text(OWN_RTL)
    return tmp_path


def _staged(project: Path):
    d = project / "phase2/stage1/rtl"
    return sorted(p.name for p in d.glob("*")) if d.is_dir() else []


@pytest.mark.parametrize("route", ["input/vendor_rtl",
                                   "input/design_src/impl/rtl"])
def test_the_generator_declines_when_the_design_ships_its_own_rtl(tmp_path,
                                                                  route):
    p = _project(tmp_path, route)
    res = D._try_deterministic_rtl_dispatch(p, 0.0)
    assert res is not None and res.status == "SKIPPED-CONDITION", res
    assert _staged(p) == [], "nothing may be written before consume runs"
    assert "403" in json.dumps(getattr(res, "extras", {}) or {})


@pytest.mark.parametrize("route", ["input/vendor_rtl",
                                   "input/design_src/impl/rtl"])
def test_the_design_implementation_reaches_the_rtl_dir(tmp_path, route):
    """The end state that actually matters: after the declined dispatch, the
    design's OWN file is what the flow will synthesise."""
    p = _project(tmp_path, route)
    D._try_deterministic_rtl_dispatch(p, 0.0)
    R.consume_reused_ip_rtl(p)
    assert "TopModule.v" in _staged(p)
    assert "TopModule.sv" not in _staged(p)


def test_without_shipped_rtl_the_generator_still_runs(tmp_path):
    """The paired half. A guard that simply never generates would satisfy
    every assertion above and delete the feature."""
    p = _project(tmp_path)
    res = D._try_deterministic_rtl_dispatch(p, 0.0)
    assert res is not None and res.status == "PASS", res
    assert "TopModule.sv" in _staged(p)


def test_a_testbench_only_tree_is_not_an_implementation(tmp_path):
    """`candidate_source_dirs` deliberately excludes oracle / harness
    segments. A design that ships only a TB has shipped no implementation,
    and refusing to generate for it would be over-suppression."""
    p = _project(tmp_path)
    tb = p / "input/design_src/tb"
    tb.mkdir(parents=True)
    (tb / "tb_top.v").write_text("module tb; endmodule\n")
    res = D._try_deterministic_rtl_dispatch(p, 0.0)
    assert res is not None and res.status == "PASS", res
    assert "TopModule.sv" in _staged(p)


def test_the_probe_never_blocks_generation_when_it_cannot_look(tmp_path,
                                                               monkeypatch):
    """The guard's job is to decline an OVERWRITE, never to be the reason a
    run cannot generate. If the source-route enumeration raises, generation
    proceeds exactly as before."""
    p = _project(tmp_path, "input/vendor_rtl")

    def _boom(_project):
        raise RuntimeError("enumeration unavailable")

    monkeypatch.setattr(R, "candidate_source_dirs", _boom)
    res = D._try_deterministic_rtl_dispatch(p, 0.0)
    assert res is not None and res.status == "PASS", res
