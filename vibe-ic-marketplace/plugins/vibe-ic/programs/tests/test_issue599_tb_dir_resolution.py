"""#599 step 4 — the TB gates looked in one directory and the flow writes another.

Step 4 is the simulation step. It was credited on a run that had four L10 test
cases and a real testbench on disk, with NO conformance and NO coverage
measurement, because:

  * `l10_tb_conformance_check` carried its own candidate list (ORGANIC #572)
    and `sim_full_stack` was not in it;
  * `l12_tb_coverage_check` carried NO fallback at all — `sim/tb` or an error.

Two gates answering one question from two independently incomplete views. The
answer now lives in `_path_layout.resolve_tb_dir` so there is one.

MEASURED over the tracked corpus, which is why this is not a one-design quirk:

    sim_full_stack/ holds a testbench   29 project(s)
    sim/            holds a testbench   11

    projects with a phase2/stage1      178
      already resolved by the old default 9
      NEWLY resolvable                   23
      still no testbench anywhere       146

DIRECTION. This makes the gates DO work they were skipping, so a design that was
credited without measurement can now be measured and fail. That is the point:
the previous verdict was not a pass, it was an absence wearing one. 146 projects
genuinely have no testbench and are unaffected.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PL = _load("_path_layout")


def _tb(project, rel, name="tb_x.v"):
    d = project / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("module tb_x; endmodule\n", encoding="utf-8")
    return d


# ── the resolver answers where the testbench IS ─────────────────────────────
def test_the_full_stack_directory_is_found(tmp_path):
    """The location the flow itself writes, and the one the corpus mostly
    uses. Absent from the candidate list until now."""
    want = _tb(tmp_path, "phase2/stage1/sim_full_stack", "tb_x_full.v")
    assert PL.resolve_tb_dir(tmp_path) == want


def test_the_canonical_directory_still_wins_when_it_has_one(tmp_path):
    """LOAD-BEARING. Adding a location must not move projects that were
    already resolving correctly — 9 of them in the corpus."""
    canon = _tb(tmp_path, "phase2/stage1/sim/tb")
    _tb(tmp_path, "phase2/stage1/sim_full_stack", "tb_x_full.v")
    assert PL.resolve_tb_dir(tmp_path) == canon


def test_the_sim_root_is_still_found(tmp_path):
    """ORGANIC #572's case — testbenches at the sim/ root — must not regress."""
    want = _tb(tmp_path, "phase2/stage1/sim")
    assert PL.resolve_tb_dir(tmp_path) == want


def test_an_explicit_path_is_honoured_first(tmp_path):
    other = _tb(tmp_path, "custom/place")
    _tb(tmp_path, "phase2/stage1/sim_full_stack", "tb_x_full.v")
    assert PL.resolve_tb_dir(tmp_path, "custom/place") == other


def test_a_project_with_no_testbench_anywhere_returns_none(tmp_path):
    """"I found nowhere" and "the default path is missing" are different
    claims, and 146 corpus projects are genuinely in the first."""
    (tmp_path / "phase2/stage1/sim").mkdir(parents=True)
    assert PL.resolve_tb_dir(tmp_path) is None


def test_a_directory_that_exists_but_holds_nothing_is_not_the_answer(tmp_path):
    """An empty `sim/tb` used to satisfy the old default and produce a
    measurement over zero files."""
    (tmp_path / "phase2/stage1/sim/tb").mkdir(parents=True)
    want = _tb(tmp_path, "phase2/stage1/sim_full_stack", "tb_x_full.v")
    assert PL.resolve_tb_dir(tmp_path) == want


# ── both gates use it, which is the point ───────────────────────────────────
def test_l12_no_longer_assumes_the_path():
    src = (_PROGRAMS / "l12_tb_coverage_check.py").read_text(encoding="utf-8")
    assert "_pl.resolve_tb_dir(project)" in src, (
        "l12 is back to `sim_dir(project)/'tb'` or an error, so a project "
        "holding a real testbench reports 'TB dir not found'")


def test_l10_delegates_rather_than_keeping_a_second_list():
    src = (_PROGRAMS / "l10_tb_conformance_check.py").read_text(encoding="utf-8")
    assert "_pl.resolve_tb_dir(" in src, "l10 no longer shares the resolution"
    body = src[src.index("def _resolve_tb_dir"):][:1800]
    assert '"phase2/stage1/sim/tb", "phase2/stage1/sim",' not in body, (
        "the private candidate list is back — two gates with two views of one "
        "question is how step 4 got credited without a measurement")


def test_the_shared_list_actually_contains_the_full_stack_location():
    """Guards against the list being edited back. Named, not inferred."""
    assert "phase2/stage1/sim_full_stack" in PL._TB_DIR_CANDIDATES


# ── the corpus ──────────────────────────────────────────────────────────────
def test_the_corpus_flip_is_the_measured_one():
    """Not a golden number — a bound. If this drops to zero the resolver has
    stopped finding anything; if it jumps, it is matching things it should not."""
    root = _REPO / "benchmark-data"
    if not root.is_dir():
        import pytest
        pytest.skip("corpus absent")
    projects = {d.parents[1] for d in root.rglob("phase2/stage1") if d.is_dir()}
    legacy = {p for p in projects
              if PL._holds_testbench(p / "phase2/stage1/sim/tb")}
    resolved = {p for p in projects if PL.resolve_tb_dir(p) is not None}
    newly = resolved - legacy
    assert len(newly) >= 15, (
        f"only {len(newly)} project(s) newly resolve; 23 were measured when "
        f"this landed")
    assert legacy <= resolved, (
        "a project the old default resolved no longer resolves — the change "
        "was supposed to be additive")
