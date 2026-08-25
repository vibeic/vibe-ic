#!/usr/bin/env python3
"""A live-derived figure must be derived WHEREVER IT SITS, and the gate must
say how much of the page it actually guards.

WHAT WENT WRONG
===============
``tools/gen_matrix_census.py --check`` regenerates a marked block and
compares it with the committed one. ``splice()`` is
``text[:start] + block + text[stop + len(END):]`` — everything outside the two
markers is returned verbatim and therefore compares equal by construction,
whatever it says. The block is 36 lines of a 501-line README.

Measured on ``origin/main`` at ``8ad04f45``, five live-derived figures sat
outside it and were stale:

    matrix/README.md:132   blocks_on present 62 / non-empty 60  (live 63/61)
    matrix/README.md:141   "all 126 required_outputs entries"   (live 133)
    matrix/README.md:232   "150 blocking clauses"               (live 160)
    matrix/flowref.py:61   "126 entries over 61 steps"          (live 133)
    test_matrix_d2_falsifiable.py:186  "150 blocking clauses"        (live 160)

The first was invalidated by ``332b9985`` (#929) — the exact commit the census
gate's own landing message names as the reason that gate exists. The generated
block was repaired by that landing; the prose was not, and ``--check`` printed
``[PASS] 63x8 census fresh`` over all five.

WHAT THIS FILE LOCKS
====================
1. An ANCHORED figure that disagrees with the tree is REPORTED and the gate
   goes red. This is the assertion that fails on the unfixed generator.
2. An anchored figure that AGREES is not reported. A gate that only ever says
   no is a ban, not a check, and a red that costs nothing to earn proves
   nothing about the green.
3. An anchor naming no binding is reported. A placeholder that cannot render
   reads as derived and is not.
4. An anchor sweep that found NO anchors exits 2. "No drift" over an empty
   population is the absence of a result, not a clean one (vibe-ic#564).
5. The COMMITTED corpus is fresh — the assertion that would have caught #961,
   taken against the real tree rather than a fixture.
6. Every verdict DISCLOSES coverage: how many figures the gate guards and how
   many stated population figures in the same files it does not. Both numbers
   are derived from the sweep; neither is a literal.
7. PAIRED GUARD, unchanged behaviour: the generated census block is still
   guarded exactly as before — the markers are intact, nothing anchored has
   been smuggled inside them, and the anchor pass rewrites zero bytes of it.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/test_matrix_figure_coverage.py -q
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

GEN = repo_path_or_missing("tools", "gen_matrix_census.py")
README = plugin_path("programs", "tests", "matrix", "README.md")
PLUGIN = plugin_path()

#: Same reasoning as `test_matrix_census_freshness._CLI_TIMEOUT_S`: the
#: pytest harness bound is 180 s, so any ONE blocking call may take at most
#: 180 // 3. MEASURED on this tree, `--check-figures` over the real corpus is
#: 1.4 s — it parses one yaml and reads 24 files, and deliberately does NOT
#: touch the two-minute census. The bound is the harness ceiling, not a
#: measurement of this call, so it cannot mask a regression in its cost.
_CLI_TIMEOUT_S = 60


#: Anchors are ASSEMBLED, never written as a literal in this file.
#:
#: MEASURED, not anticipated: written literally, every fixture anchor below was
#: swept as part of the real corpus -- this module contains the token
#: `flowref`, so it IS a corpus document -- and
#: `test_every_anchored_figure_in_the_committed_corpus_is_fresh` failed on two
#: deliberately-wrong fixtures. A test whose fixtures are indistinguishable
#: from the tree it audits corrupts the audit.
_OPEN = "<!" + "--figure:"


def _anchor(value, name: str) -> str:
    return f"{value}{_OPEN}{name}-->"


def _gen_or_skip() -> Path:
    if not GEN.exists():
        pytest.skip(
            f"generator not present at {GEN} (mirror tree); figure freshness "
            f"is enforced in the source-of-truth tree only")
    return GEN


def _load_generator():
    """The generator imported as a module, without writing bytecode.

    Same posture as the sibling freshness test: a `__main__` script is never
    byte-compiled to disk, so an import that left a `__pycache__` behind would
    enlarge the very tree other gates audit.
    """
    spec = importlib.util.spec_from_file_location(
        "_gen_matrix_census_figures", str(_gen_or_skip()))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def _run(args, timeout=_CLI_TIMEOUT_S):
    return subprocess.run(
        [sys.executable, str(_gen_or_skip()), *args],
        capture_output=True, text=True, timeout=timeout)


def _corpus(tmp_path: Path, body: str) -> Path:
    """A one-document corpus.

    ``flowref`` is in the text because corpus membership is decided by content
    — the generator discovers the documents that speak about the substrate
    rather than carrying a list of them. A fixture that omitted the token would
    silently be swept as an EMPTY corpus and every assertion below would pass
    for the wrong reason.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "doc.md").write_text(
        f"about matrix.flowref\n\n{body}\n", encoding="utf-8")
    return root


def _live(name: str) -> int:
    gen = _load_generator()
    return gen.CORPUS_FIGURES.evaluate(name, PLUGIN)


# ------------------------------------------------------------------ 1. RED --
def test_a_stale_anchored_figure_makes_the_gate_red():
    """The finding, as an assertion. Fails on the unfixed generator."""
    gen = _load_generator()
    live = _live("blocks_on_declared")
    text = ("blocks_on is present on "
            + _anchor(live - 1, "blocks_on_declared") + " steps")
    _updated, sites = gen.render_anchored(text, {"blocks_on_declared": live})
    assert [s.status for s in sites] == ["stale"], sites
    assert sites[0].derived == live and sites[0].stated == live - 1


def test_the_cli_goes_red_on_a_stale_anchored_figure(tmp_path):
    live = _live("blocks_on_declared")
    root = _corpus(tmp_path, "present on "
                   + _anchor(live - 1, "blocks_on_declared") + " steps")
    red = _run(["--check-figures", "--figures-root", str(root)])
    assert red.returncode == 1, red.stdout + red.stderr
    out = red.stdout + red.stderr
    assert "blocks_on_declared" in out and str(live) in out, out
    assert "--fix-figures" in out, (
        f"the gate went red without naming the remedy:\n{out}")


# --------------------------------------------------------- 2. PAIRED GUARD --
def test_a_correct_anchored_figure_is_not_reported(tmp_path):
    """The green direction, earned rather than assumed.

    A checker that reported every anchored figure would pass test 1 and be
    useless. This is the assertion that must NOT change when the red one is
    made to fire.
    """
    live = _live("blocks_on_declared")
    root = _corpus(tmp_path, "present on "
                   + _anchor(live, "blocks_on_declared") + " steps")
    green = _run(["--check-figures", "--figures-root", str(root)])
    assert green.returncode == 0, green.stdout + green.stderr
    assert "[PASS]" in green.stdout, green.stdout


# ------------------------------------------------------------- 3. UNBOUND --
def test_an_anchor_with_no_binding_is_reported(tmp_path):
    root = _corpus(tmp_path, "there are "
                   + _anchor(7, "no_such_binding") + " steps")
    rc = _run(["--check-figures", "--figures-root", str(root)])
    assert rc.returncode == 1, rc.stdout + rc.stderr
    assert "no_such_binding" in rc.stdout + rc.stderr


# ------------------------------------------------------ 4. NOTHING_SCANNED --
def test_an_anchor_sweep_over_no_anchors_is_not_a_pass(tmp_path):
    """rc 2, not rc 0. This gate is subject to its own rule."""
    root = _corpus(tmp_path, "flowref says there are 63 steps and no anchors")
    rc = _run(["--check-figures", "--figures-root", str(root)])
    assert rc.returncode == 2, rc.stdout + rc.stderr
    assert "NOTHING_SCANNED" in rc.stdout + rc.stderr


def test_an_empty_corpus_is_not_a_pass(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = _run(["--check-figures", "--figures-root", str(empty)])
    assert rc.returncode == 2, rc.stdout + rc.stderr


# ------------------------------------------------------ 5. THE REAL CORPUS --
def test_every_anchored_figure_in_the_committed_corpus_is_fresh():
    """#961, asserted against the tree instead of a fixture."""
    gen = _load_generator()
    report = gen.figure_report(PLUGIN, gen.FIGURES_ROOT)
    stale = [(f["rel"], s) for f in report["files"] for s in f["stale"]]
    assert not stale, (
        "anchored figure(s) disagree with the flow yaml; re-run "
        "`python3 tools/gen_matrix_census.py --fix-figures`:\n"
        + "\n".join(f"  {rel}:{s['line']}  {s['name']} states {s['stated']}, "
                    f"tree says {s['derived']}" for rel, s in stale))
    assert report["guarded_anchored"], (
        "NOTHING_SCANNED: the committed corpus carries no anchored figure at "
        "all, so this test passed without comparing a single number.")


def test_the_five_figures_the_issue_named_are_anchored_and_live():
    """Named by BINDING, not by line number, so the test survives an edit.

    Each of the five stale figures was one of these derivations. A binding that
    stops being anchored anywhere in the corpus means the prose it kept honest
    has gone back to being typed.
    """
    gen = _load_generator()
    report = gen.figure_report(PLUGIN, gen.FIGURES_ROOT)
    anchored = {a["name"] for f in report["files"] for a in f["anchored"]}
    for name in ("blocks_on_declared", "blocks_on_nonempty",
                 "required_output_entries", "blocking_clauses", "gated_steps"):
        assert name in anchored, (
            f"{{figure:{name}}} is anchored nowhere in the corpus; one of the "
            f"five figures vibe-ic#961 measured stale is a typed number again")


# ------------------------------------------------------------ 6. COVERAGE --
def test_the_verdict_discloses_how_much_it_guards_and_how_much_it_does_not():
    """A PASS that hides its denominator is the defect, not the fix."""
    gen = _load_generator()
    report = gen.figure_report(PLUGIN, gen.FIGURES_ROOT)
    lines = "\n".join(gen.coverage_lines(report))
    assert str(report["guarded_total"]) in lines
    assert str(report["unguarded_total"]) in lines
    assert str(report["corpus_files"]) in lines
    assert report["guarded_total"] > 0 and report["corpus_files"] > 1, report
    # The unguarded population is DISCOVERED. Asserting it is non-zero is not a
    # target -- it is the proof that the denominator is measured rather than
    # declared equal to the numerator, which is how a coverage line lies.
    assert report["unguarded_total"] > 0, (
        "the coverage report claims this gate guards every stated figure in "
        "24-odd files of prose. That is not credible; a denominator that "
        "collapses onto the numerator means the discovery half stopped working")
    assert (report["unguarded_pinned"] + report["unguarded_unpinned"]
            == report["unguarded_total"])


def test_the_cli_prints_the_coverage_on_a_green_verdict(tmp_path):
    live = _live("flow_steps")
    root = _corpus(tmp_path, "the flow has "
                   + _anchor(live, "flow_steps")
                   + " steps, and 90 other files nobody derives")
    green = _run(["--check-figures", "--figures-root", str(root)])
    assert green.returncode == 0, green.stdout + green.stderr
    assert "[COVERAGE]" in green.stdout, green.stdout
    assert "does NOT guard" in green.stdout, green.stdout


# ---------------------------------------------------------------- 7. WRITE --
def test_fix_figures_repairs_the_prose_and_is_idempotent(tmp_path):
    live = _live("flow_steps")
    root = _corpus(tmp_path, "the flow has "
                   + _anchor(3, "flow_steps") + " steps")
    doc = root / "doc.md"
    fixed = _run(["--fix-figures", "--figures-root", str(root)])
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert _anchor(live, "flow_steps") in doc.read_text(encoding="utf-8")
    before = doc.read_text(encoding="utf-8")
    again = _run(["--fix-figures", "--figures-root", str(root)])
    assert again.returncode == 0
    assert doc.read_text(encoding="utf-8") == before, (
        "a second --fix-figures changed the document; a generator that is not "
        "idempotent cannot be used to decide whether a tree is fresh")


# --------------------------------------------- 8. PAIRED GUARD: the block --
def test_the_generated_census_block_is_guarded_exactly_as_before():
    """The block contract must survive the change that reaches outside it.

    Three properties, all of which held before this change and must still:
    the markers exist, the block is a NO-OP for the anchor pass (so the two
    mechanisms cannot fight over the same bytes), and no anchor has been
    smuggled inside the markers where the block generator would overwrite it
    on the next run.
    """
    gen = _load_generator()
    text = README.read_text(encoding="utf-8")
    start, stop = text.find(gen.BEGIN), text.find(gen.END)
    assert 0 <= start < stop, "the generated-census markers are gone"
    block = text[start:stop + len(gen.END)]

    from _derived_corpus_figure import anchored_figures
    assert anchored_figures(block) == [], (
        "an anchored figure sits INSIDE the generated block. The block is "
        "rewritten wholesale on every run, so the anchor would be destroyed "
        "and its binding silently stop being checked.")

    values = gen.CORPUS_FIGURES.evaluate_all(PLUGIN)
    rewritten, _sites = gen.render_anchored(block, values)
    assert rewritten == block, (
        "the anchor pass rewrote bytes inside the generated census block")

    # And the published total row still parses, which is what the sibling
    # freshness test asserts against the live census.
    assert "| **total** |" in block, block[:400]
