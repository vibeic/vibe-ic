#!/usr/bin/env python3
"""The census repair tool may not be stopped by what it cannot repair.

WHAT WENT WRONG (vibe-ic#2004)
==============================
``tools/gen_flow_matrix_census.py --fix`` is the ONE command every stale-census
message in this repository points at. It repairs in two stages: the anchored
figures in ``flow_matrix/flowref.py`` first, the generated census block in
``flow_matrix/README.md`` second.

The second stage went through ``enforcement_census()``, whose nested outcome
run declares NORECORD when ANY non-cell test in the nine dimension modules is
red. That assertion left ``main()`` as an uncaught ``AssertionError``.

MEASURED on a fresh clone of ``origin/main`` at ``d453eaca6`` (8hd-3,
2026-09-02), the tool run exactly as its own message instructs::

    rewrote anchored figures in 1 file(s): flow_matrix/flowref.py
    Traceback (most recent call last):
      ...
    AssertionError: the nested outcome run produced red test report(s)
    outside the matrix cell join. ... this run is NORECORD:
    [('...test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned', 'failed'),
     ('...test_matrix_d2_falsifiable.py::test_d2_the_two_obstruction_gates_redden_and_only_on_content', 'failed'),
     ('...test_matrix_d5_deps_correct.py::...', 'failed'), x2
     ('...test_matrix_d8_missing_caught.py::...', 'failed')] x4

Two harms, and the second is the one that spreads:

1. the repair could not complete PRECISELY WHEN A REPAIR WAS NEEDED — the tree
   was drifted, which is the only reason to run ``--fix`` at all;
2. it left the tree HALF-REPAIRED. ``flowref.py`` was rewritten and the README
   block was not, so every measurement checkout the tool was pointed at came
   back dirty in one tracked file, for no gain.

AND THE FIX-SHAPE THE ISSUE PROPOSED CANNOT WORK — MEASURED
-----------------------------------------------------------
vibe-ic#2004 proposed validating on the FULLY regenerated pair, or excluding
"reds that the regeneration itself is about to cure". Measured on the same
clone, with ``flowref.py`` restored to its committed state and nothing else
changed, those same eight tests are RED on the PRISTINE checkout::

    8 failed, 24 passed in 26.78s

None of them reads the census block or an anchored figure. The regeneration
cures none of them, so an exclusion of "reds about to be cured" would exclude
nothing and the deadlock would stand.

WHAT THIS FILE LOCKS
====================
The refusal FOLLOWS the write instead of replacing it.

* ``--fix`` (and the plain run) regenerate the block and THEN refuse, rc 2,
  with the foreign reds named.
* ``--check`` refuses, rc 2, and publishes no freshness verdict at all — a
  freshness verdict computed from a non-record is not a verdict.
* the NORECORD guard itself is UNWEAKENED: ``cell_outcomes()`` and
  ``enforcement_census()``, the entry points every publishing reader uses,
  still refuse a genuinely foreign red. That is the control below, and it is
  the assertion this file would rather fail than lose.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
      python3 -m pytest programs/tests/test_issue2004_census_fix_repairs_before_it_refuses.py -q
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GEN = repo_path_or_missing("tools", "gen_flow_matrix_census.py")
PLUGIN = plugin_path()

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_flow_matrix_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"

#: The synthetic foreign red. A REAL nodeid shape — module::test, no
#: parametrize id — because that shape is exactly what falls outside the cell
#: join, and a made-up one would not.
FOREIGN_NODEID = "test_matrix_d1_wiring.py::test_a_supporting_helper"

#: Assembled, never a literal: this module carries the token `flowref` (it must,
#: to describe the substrate honestly), so a literal anchor here would be swept
#: as part of the real corpus and reported as a stale figure in the tree —
#: measured on `test_flow_matrix_figure_coverage`, which learned this first.
_OPEN = "<!" + "--figure:"


def _anchor(value, name: str) -> str:
    return f"{value}{_OPEN}{name}-->"


def _gen_or_skip() -> Path:
    if not GEN.exists():
        pytest.skip(f"generator not present at {GEN} (mirror tree)")
    return GEN


def _load_generator():
    """The generator imported as a module, leaving no bytecode behind.

    Same posture as both sibling census tests: a ``__main__`` script is never
    byte-compiled to disk, so an import that wrote ``__pycache__`` would
    enlarge the tree other gates audit.
    """
    spec = importlib.util.spec_from_file_location(
        "_gen_flow_matrix_census_2004", str(_gen_or_skip()))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


#: Drives the REAL generator CLI over a SYNTHETIC census, so one run costs
#: milliseconds instead of the nine dimension modules' several minutes.
#:
#: The stub is installed in ``sys.modules`` before ``_load()`` resolves
#: ``import test_flow_matrix_coverage`` — the same interception the sibling
#: freshness test uses. EVERYTHING ELSE IS THE REAL GENERATOR: ``_load``,
#: ``census_rows_with_record``, ``render``, ``splice``, ``_run``, ``main``, the
#: partition guards, the write, and the exit codes. What the stub decides is
#: one thing only: whether this run's nested session had a red report outside
#: the cell join.
_CLI_PROBE = r"""
import runpy
import sys
import types

gen_path, out_path, mode, figures_root, foreign_nodeid = sys.argv[1:6]

NORECORD_REASON = "SYNTHETIC-NORECORD-REASON " + foreign_nodeid


class _Verdict:
    def __init__(self, label):
        self.label = label


def _dims():
    # Importable only after the generator's `_load()` has put the plugin test
    # directories on sys.path, which it does before it touches the census.
    from flow_matrix.cells import DIMENSIONS
    return DIMENSIONS


def _census():
    return {(step, dim): _Verdict(label)
            for dim in _dims()
            for step, label in (("1", "ENFORCED"),
                                ("2", "WAIVED"),
                                ("3", "NA"))}


def enforcement_census_with_record():
    foreign = ((foreign_nodeid, "failed"),) if mode.startswith("norecord") else ()
    return _census(), foreign


def enforcement_census():
    census, foreign = enforcement_census_with_record()
    assert not foreign, norecord_foreign_red_reason(foreign)
    return census


def norecord_foreign_red_reason(foreign_reds):
    return NORECORD_REASON


def substitution_census():
    from flow_matrix import substitution as SUB
    return {("1", dim): SUB.OWN_MECHANISM for dim in _dims()}


stub = types.ModuleType("test_flow_matrix_coverage")
stub.enforcement_census = enforcement_census
stub.enforcement_census_with_record = enforcement_census_with_record
stub.norecord_foreign_red_reason = norecord_foreign_red_reason
stub.substitution_census = substitution_census
sys.modules["test_flow_matrix_coverage"] = stub

sys.argv = ["gen_flow_matrix_census.py", "--out", out_path,
            "--figures-root", figures_root]
if mode.endswith("check"):
    sys.argv.append("--check")
runpy.run_path(gen_path, run_name="__main__")
"""


def _fresh_corpus(tmp_path: Path) -> Path:
    """A one-document anchored corpus that is CORRECT for this tree.

    The value is re-derived from the generator's own binding table rather than
    typed, so this fixture cannot go stale the way the corpus it stands in for
    did. Without it the control arm below could not tell "the census refused"
    from "some anchor in the real tree happens to be stale today", which is
    the confusion this whole gate exists to remove.
    """
    gen = _load_generator()
    live = gen.CORPUS_FIGURES.evaluate("flow_steps", PLUGIN)
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "doc.md").write_text(
        "about flow_matrix.flowref\n\nthe flow declares "
        + _anchor(live, "flow_steps") + " steps\n", encoding="utf-8")
    return root


def _readme(tmp_path: Path, body: str = "placeholder") -> Path:
    path = tmp_path / "README.md"
    path.write_text(f"before\n{BEGIN}\n{body}\n{END}\nafter\n", encoding="utf-8")
    return path


def _run_probe(tmp_path: Path, mode: str):
    readme = _readme(tmp_path)
    corpus = _fresh_corpus(tmp_path)
    proc = _pr.run(
        [sys.executable, "-c", _CLI_PROBE, str(_gen_or_skip()), str(readme),
         mode, str(corpus), FOREIGN_NODEID],
        capture_output=True, text=True)
    return proc, readme


# ------------------------------------------------------- 1. THE DEADLOCK --
def test_fix_writes_the_census_block_even_when_the_run_is_norecord(tmp_path):
    """THE REPRODUCTION. Fails against the pre-fix generator.

    Before the fix this run died inside ``census_rows`` and the README was
    left holding ``placeholder`` — the half-repair, in one assertion.
    """
    proc, readme = _run_probe(tmp_path, "norecord")
    body = readme.read_text(encoding="utf-8")
    assert "placeholder" not in body and BEGIN in body and END in body, (
        f"the repair did not complete: the census block was never written, "
        f"which is the deadlock this issue is about.\n"
        f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}\n---\n{body}")
    assert body.startswith("before\n") and body.endswith("after\n"), (
        f"the generator wrote outside its own markers:\n{body}")


def test_fix_still_refuses_after_it_has_written(tmp_path):
    """Completing the repair is not the same as forgiving the condition."""
    proc, _readme = _run_probe(tmp_path, "norecord")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, (
        f"a NORECORD run exited {proc.returncode}. Writing the artefact does "
        f"not make the run a record; rc 2 is the house code for a gate that "
        f"could not look.\n{out}")
    assert "NORECORD" in out and FOREIGN_NODEID in out, (
        f"the refusal did not name the condition or the red it refused on, so "
        f"a reader cannot act on it:\n{out}")


def test_the_refusal_does_not_send_the_reader_back_to_this_generator(tmp_path):
    """The remedy for a foreign red is in the dimension module, not here.

    A refusal that says "re-run ``--fix``" would loop the reader through the
    exact command that just refused. MEASURED: none of the eight reds that
    produced this issue is curable by any run of this program.
    """
    proc, _readme = _run_probe(tmp_path, "norecord")
    out = proc.stdout + proc.stderr
    tail = out[out.index("NORECORD"):]
    assert "cannot cure" in tail, (
        f"the refusal does not say that re-running cannot cure it:\n{tail}")


# ------------------------------------------------ 2. THE PAIRED CONTROL --
def test_a_record_run_writes_and_exits_zero(tmp_path):
    """The green direction, earned rather than assumed.

    Without this, a generator that had learned to return 2 unconditionally
    would satisfy every assertion above.
    """
    proc, readme = _run_probe(tmp_path, "record")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"a run with no foreign red exited {proc.returncode}; the refusal is "
        f"firing on something other than the condition it names.\n{out}")
    assert "placeholder" not in readme.read_text(encoding="utf-8"), out
    assert "NORECORD" not in out, out


def test_check_refuses_a_norecord_run_but_still_reports_the_block(tmp_path):
    """``--check`` may not PASS over a non-record — and may not go silent either.

    Two different facts. Staleness is a property of the block; NORECORD is a
    property of the nested session. The first draft of this fix refused before
    comparing, and MEASURED on the regenerated tree that produced a `--check`
    which printed the refusal and said nothing whatever about the block it had
    just been asked about — a reader had no way to learn whether the derived
    pair in the tree was the right one. Both are printed; only one is the
    verdict.
    """
    proc, _readme = _run_probe(tmp_path, "norecord-check")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out
    assert "NORECORD" in out, out
    assert "census fresh" not in out, (
        f"`--check` published a PASS over a run it had already declared "
        f"NORECORD. A freshness verdict computed from a non-record is not a "
        f"verdict.\n{out}")
    # The fixture README holds `placeholder`, so the block IS stale and the
    # finding must survive the refusal that outranks it.
    assert "census block is stale" in out, (
        f"`--check` refused without saying whether the block it was asked "
        f"about is stale; the reader learns nothing about their tree.\n{out}")


# --------------------------------- 3. THE GUARD ITSELF, UNWEAKENED --
def test_the_norecord_guard_still_refuses_a_genuinely_foreign_red():
    """The line vibe-ic#2004 said must never move. In-process, no nested run.

    ``_cell_outcomes_from_reports`` is what every PUBLISHING reader reaches
    through, and it still raises. This drives it on a hand-built pair of
    reports — one green cell, one red helper — so the assertion is exercised
    without paying for the nine dimension modules.
    """
    import test_flow_matrix_coverage as CV

    passed = [{"when": "call", "outcome": "passed", "wasxfail": False,
               "longrepr": ""}]
    failed = [{"when": "call", "outcome": "failed", "wasxfail": False,
               "longrepr": "a supporting check refused the session"}]
    reports = {
        "test_matrix_d1_example.py::test_cell[stepD1]": passed,
        f"test_matrix_d1_example.py::{FOREIGN_NODEID.split('::')[1]}": failed,
    }
    by_file, live = {"test_matrix_d1_example.py": 1}, {"D1"}

    with pytest.raises(AssertionError, match="outside the matrix cell join"):
        CV._cell_outcomes_from_reports(reports, by_file, live)

    # ...and the SAME pair, through the seam the repair tool uses, hands the
    # red back instead of raising. Both halves in one test because the point
    # is the DIFFERENCE between them, and a reader who sees only one of the
    # two cannot tell a weakened guard from a second entry point.
    join = getattr(CV, "_join_cell_reports", None)
    assert join is not None, (
        "the repair tool's seam is missing; without it the only way to obtain "
        "the cells is to accept the refusal, which is the deadlock")
    cells, foreign = join(reports, by_file, live)
    assert cells and [n for n, _ in foreign] == [
        f"test_matrix_d1_example.py::{FOREIGN_NODEID.split('::')[1]}"], (
        f"the seam did not report the foreign red it declined to raise on: "
        f"{foreign}")


def test_one_vocabulary_for_the_condition():
    """The refusal the guard raises and the one the generator prints are one.

    Two sentences for one state is how a reader comes to believe there are two
    states. The generator asks the coverage module for the words rather than
    writing its own, and this is that contract.
    """
    import test_flow_matrix_coverage as CV

    reason = getattr(CV, "norecord_foreign_red_reason", None)
    assert callable(reason), (
        "the coverage module publishes no shared NORECORD sentence, so the "
        "generator has to invent one")
    foreign = [(FOREIGN_NODEID, "failed")]
    text = reason(foreign)
    assert "outside the matrix cell join" in text and FOREIGN_NODEID in text

    src = _gen_or_skip().read_text(encoding="utf-8")
    assert "norecord_foreign_red_reason" in src, (
        "the generator no longer asks the coverage module for the sentence")
    assert not re.search(r"outside the matrix cell join", src), (
        "the generator has re-typed the guard's sentence instead of asking "
        "for it; the two will drift")
