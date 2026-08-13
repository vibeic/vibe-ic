#!/usr/bin/env python3
"""The published 63x8 census must reproduce, and it must carry its own caveats.

WHAT WENT WRONG
===============
``matrix_63x8/README.md`` published a hand-written census table::

    | **total** |  | **483** | **9** | **12** |

and, two lines underneath it, the command that disproves it. Run on
``origin/main`` at ``dee025059`` on 2026-08-09::

    Counter({'ENFORCED': 481, 'NA': 12, 'WAIVED': 11})

Four rows had drifted. Nothing recomputed the table, so the campaign's headline
number was a number someone typed once — while every cell underneath it was
recomputed live on every run, which is the entire premise of the suite.

The second half is worse than the drift. Dimension 8 substitutes a stand-in gate
for most of its cells; 45 of its 61 ENFORCED cells never touch the gate the step
declares. That is disclosed, carefully, in its module docstring, and then the
census added eight rows together and the disclosure was gone. A caveat that does
not travel with the number is not a caveat.

WHAT THIS FILE LOCKS
====================
1. The block is GENERATED. ``tools/gen_matrix_63x8_census.py --check`` re-derives
   it from the live suite and this test fails on any drift — the same shape as
   ``test_programs_index_freshness.py`` for ``programs/INDEX.md``.
2. The published figures EQUAL the live census, checked here independently of
   the generator's own diff. If both the generator and the committed README were
   wrong in the same way, (1) would still pass; this does not.
3. The substituted cells are published as their own column and are NEVER inside
   a figure presented as enforcement. This is the assertion that fails on the
   unfixed tree.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/test_matrix_63x8_census_freshness.py -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

from matrix_63x8 import substitution as SUB

import test_matrix_63x8_coverage as CV

GEN = repo_path_or_missing("tools", "gen_matrix_63x8_census.py")
README = plugin_path("programs", "tests", "matrix_63x8", "README.md")

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_matrix_63x8_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"


def _block() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    stop = text.find(END)
    assert 0 <= start < stop, (
        f"{README} has no generated-census block; the markers are what make "
        f"the published figure derived rather than typed, and without them a "
        f"hand edit is invisible to the freshness check"
    )
    return text[start:stop + len(END)]


def _total_row(block: str):
    """``(own, substituted, undeclared, contradicted, waived, na)``.

    Six figures, not five. CONTRADICTED became a column of its own when the
    three ENFORCED columns were moved onto the enforcement axis: they now span
    the ENFORCED cells only, so without a column of its own a contradicted cell
    would appear in no column at all and the row would silently drop 28 cells.
    """
    m = re.search(
        r"\|\s*\*\*total\*\*\s*\|[^|]*\|"
        r"\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|"
        r"\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|",
        block)
    assert m, (
        f"no ``**total**`` row with six bold figures found in the generated "
        f"census block. The published total is the number people quote; if it "
        f"cannot be parsed it cannot be checked.\n{block[:1200]}"
    )
    return tuple(int(g) for g in m.groups())


def test_the_census_block_is_present_and_marked_generated():
    block = _block()
    assert "DO NOT EDIT BY HAND" in block


#: Bound for the generator CLI probe below. NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict.
#:
#: The landed value was 1800 on a `gen_matrix_63x8_census.py --check` launch,
#: and simply lowering it was NOT available. MEASURED on this tree, that launch
#: takes 119.13 s idle / 136.67 s under load, and `cProfile` says where: of
#: 115.70 s total, 97.54 s is `cell_outcomes()` — all eight dimension modules
#: re-run inside a nested pytest. That work is real and it is not this change's
#: to remove, so capping the launch at 60 s would not have fixed a defect; it
#: would have made a working test fail on the clock.
#:
#: So the call is SPLIT along the seam the measurement exposes:
#:
#:   * `test_the_census_block_is_fresh` asserts exactly what `--check` asserts
#:     — committed text == splice(render(census_rows())) — IN-PROCESS, where
#:     every process launch underneath is a per-dimension outcome run that
#:     `test_matrix_63x8_coverage` bounds at 60 s each (measured worst module:
#:     35.18 s). It also stops one census being computed twice per session.
#:     MEASURED, this file: 136.75 s -> 116.56 s, because the sibling
#:     `test_the_published_total_equals_the_live_census` was paying 16.87 s for
#:     its own state/substitution census beside the subprocess's and now reads
#:     the `lru_cache` this test filled. The 504-cell outcome run itself still
#:     happens exactly once, as it did before.
#:   * `test_the_generator_cli_can_go_red_and_green` keeps the CLI itself under
#:     test — `main()`, `--check`, the exit codes, the stale message — in a
#:     subprocess, and makes it CHEAP by handing the generator a synthetic
#:     census through `sys.modules`.
#:
#: The count of readable bounds this gate keeps a denominator of is HELD: one
#: bound left this file, one replaced it. A green earned by making a call
#: invisible to the check is the failure this gate family exists to prevent.
_CLI_TIMEOUT_S = 60

#: Runs the real generator CLI over a SYNTHETIC census. The stub is installed
#: in `sys.modules` before `_load()` runs, so the generator's own `import
#: test_matrix_63x8_coverage` resolves to it instead of importing the real one
#: — the same interception `test_blocker_list_report_contract` uses to put a
#: program under test on a known input. Everything else is the real generator:
#: `_load`, `census_rows`, `render`, `splice`, `main`, the partition guard and
#: the exit codes.
_CLI_PROBE = r"""
import runpy
import sys
import types

gen_path, out_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]


class _Verdict:
    def __init__(self, label):
        self.label = label


def _dims():
    # Importable only after the generator's `_load()` has put the plugin test
    # directories on sys.path, which it does before it touches the census.
    from matrix_63x8.cells import DIMENSIONS
    return DIMENSIONS


def enforcement_census():
    return {(step, dim): _Verdict(label)
            for dim in _dims()
            for step, label in (("1", "ENFORCED"),
                                ("2", "WAIVED"),
                                ("3", "NA"))}


def substitution_census():
    from matrix_63x8 import substitution as SUB
    return {("1", dim): SUB.OWN_MECHANISM for dim in _dims()}


stub = types.ModuleType("test_matrix_63x8_coverage")
stub.enforcement_census = enforcement_census
stub.substitution_census = substitution_census
sys.modules["test_matrix_63x8_coverage"] = stub

sys.argv = ["gen_matrix_63x8_census.py"]
if mode == "check":
    sys.argv.append("--check")
sys.argv += ["--out", out_path]
runpy.run_path(gen_path, run_name="__main__")
"""

#: The generator's `_load()` calls `os.environ.setdefault` on this. In its own
#: subprocess that was invisible; imported, it would leak into every pytest
#: CHILD any later test in the session spawns. Set and restored around the one
#: call that needs it rather than left behind.
_AUTOLOAD_ENV = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"


def _gen_or_skip():
    if not GEN.exists():
        pytest.skip(
            f"generator not present at {GEN} (mirror tree); freshness is "
            f"enforced in the source-of-truth tree only")
    return GEN


def _load_generator():
    """The generator, imported as a module rather than launched.

    `dont_write_bytecode` is not tidiness. A `__main__` script is never
    byte-compiled to disk, so the launch this replaces left nothing behind;
    an import does, and MEASURED it moved a number a gate publishes —
    `gates are host-independent` disclosed "6 ignored path(s) present in the
    checkout and not in a fresh worktree" before and 7 after, the extra one
    being `tools/__pycache__/`. Ignored, so `git status` stays clean and the
    landing fingerprint is untouched, but a test may not enlarge the tree it
    is auditing.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_gen_matrix_63x8_census", str(_gen_or_skip()))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


#: vibe-ic#1451 — this test's cost is the WHOLE MATRIX, paid inside one test:
#: `census_rows()` -> `CV.enforcement_census` -> `_run_outcome_reports`, which
#: spawns a nested pytest per dimension module. Its aggregate cannot fit the
#: harness bound, and the arithmetic is not close:
#:
#:     _OUTCOME_TIMEOUT_S = 60s   x   8 dimension modules (d1..d8)  =  480s
#:     harness bound (tools/gatekeeper-land.sh)                     =  180s
#:
#: MEASURED on clean main: 282.27s under a 600s bound, on a host at load 145.
#: The issue reports 259.93s on a quieter one — so it straddles 180s depending
#: on what else the fleet is doing, which is the worst shape for a bound: it
#: passes for the author and kills the SESSION for the verifier.
#:
#: WHY NOTHING CAUGHT IT. `ci_harness_timeout_ceiling_check` reasons PER CALL —
#: this file's own comment above says it "permits any ONE blocking call at
#: most" — so eight sequential 60s calls each clear the ceiling while their sum
#: cannot. The inner bounds are individually compliant and collectively
#: impossible. That gap is the general finding; see #1451.
#:
#: WHY A MARKER RATHER THAN A SMALLER INNER BOUND. Cutting `_OUTCOME_TIMEOUT_S`
#: to fit 8 runs inside 180s means 22s per dimension module, which would start
#: converting slow-but-honest module runs into the "did not finish" assertion —
#: trading a session kill for a false red. The honest move is for a genuinely
#: expensive test to DECLARE the time it needs, so it either completes or fails
#: on its own instead of taking every other file's verdict down with it.
#: 600 = the 480s structural worst case plus headroom for the census render.
@pytest.mark.timeout(600)
def test_the_census_block_is_fresh():
    """Re-derive it and refuse any drift.

    This is `--check`, asserted directly instead of through a launch whose own
    bound this file's harness could never let fire — see `_CLI_TIMEOUT_S`. The
    predicate is the generator's own: `main()` computes
    `splice(text, render(*census_rows()))` and exits 1 when that differs from
    the committed text, and so does this.
    """
    gen = _load_generator()
    prev = os.environ.get(_AUTOLOAD_ENV)
    try:
        rows, totals = gen.census_rows()
    finally:
        if prev is None:
            os.environ.pop(_AUTOLOAD_ENV, None)
        else:
            os.environ[_AUTOLOAD_ENV] = prev
    assert rows and totals["cells"], (
        f"NOTHING_SCANNED: the live census produced {len(rows)} dimension "
        f"row(s) over {totals.get('cells', 0)} cell(s). A census rendered over "
        f"zero cells matches an empty table trivially, so this is NOT a pass — "
        f"it is the generator's own rc-2 condition, asserted here.")
    text = README.read_text(encoding="utf-8")
    rendered = gen.render(rows, totals)
    assert gen.splice(text, rendered) == text, (
        f"the census in {README} is stale — re-run "
        f"`python3 tools/gen_matrix_63x8_census.py`.\n"
        f"committed:\n{_block()[:1200]}\n\n"
        f"re-derived:\n{rendered[:1200]}")


def test_the_generator_cli_can_go_red_and_green(tmp_path):
    """The CLI itself, in both directions, on a census that costs under a second.

    `test_the_census_block_is_fresh` asserts the generator's PREDICATE. It does
    not exercise `main()`, `--check`, the exit codes or the stale message, and
    on a tree whose census happens to be fresh nothing would notice a `--check`
    that had stopped being able to return 1 at all. That is the shape this repo
    calls a check that lies, so the red direction is proved here, not assumed.
    """
    gen = _gen_or_skip()
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{BEGIN}\nplaceholder\n{END}\nafter\n",
                      encoding="utf-8")

    def run(mode):
        return subprocess.run(
            [sys.executable, "-c", _CLI_PROBE, str(gen), str(readme), mode],
            capture_output=True, text=True, timeout=_CLI_TIMEOUT_S)

    wrote = run("write")
    assert wrote.returncode == 0, wrote.stdout + wrote.stderr
    body = readme.read_text(encoding="utf-8")
    assert BEGIN in body and END in body and "placeholder" not in body, (
        f"the generator did not replace the marked block:\n{body}")
    assert body.startswith("before\n") and body.endswith("after\n"), (
        f"the generator wrote outside its own markers:\n{body}")

    green = run("check")
    assert green.returncode == 0, (
        f"`--check` refuses a block it has just written itself, so a 0 from it "
        f"on the real README would mean nothing.\n"
        f"{green.stdout}\n{green.stderr}")

    # The mutation: one digit of the generated total row, nothing else.
    mutated = re.sub(r"\| \*\*(\d+)\*\* \|", r"| **\g<1>9** |", body, count=1)
    assert mutated != body, f"the mutation did not apply:\n{body}"
    readme.write_text(mutated, encoding="utf-8")

    red = run("check")
    assert red.returncode == 1, (
        f"`--check` returned {red.returncode} on a block whose published total "
        f"had been edited by hand. A freshness check that cannot go red is not "
        f"a freshness check.\n{red.stdout}\n{red.stderr}")
    assert "stale" in red.stderr, (
        f"`--check` went red without naming the drift or the remedy:\n"
        f"{red.stderr}")


def test_the_published_total_equals_the_live_census():
    """Independent of the generator: the numbers on the page vs the tree.

    ``test_the_census_block_is_fresh`` compares the page against what the
    generator would emit. That is one source checked against itself: a
    generator that computed the wrong thing would agree with a README carrying
    the wrong thing, and both would be green. This recomputes from
    ``enforcement_census()`` / ``substitution_census()`` directly.

    INDEPENDENT IN SOURCE IS NOT INDEPENDENT IN AXIS. This test recomputed from
    ``state_census()`` -- the CONFIGURATION axis -- and so agreed with a
    generator that was wrong the same way. vibe-ic#898 moved the generator onto
    ``enforcement_census()`` and left this check behind, which is why the fold
    it was written to catch survived underneath it: the published ENFORCED
    split summed to 481 while the headline two lines above said 453, and this
    assertion passed, because 481 was exactly what the wrong axis predicted.
    A second opinion taken from the same mistaken premise is not a second
    opinion.
    """
    own, substituted, undeclared, contradicted, waived, na = _total_row(_block())
    states = {k: v.label for k, v in CV.enforcement_census().items()}
    subs = {k: v for k, v in CV.substitution_census().items()
            if states.get(k) == "ENFORCED"}
    live = {
        "ENFORCED": sum(1 for v in states.values() if v == "ENFORCED"),
        "CONTRADICTED": sum(
            1 for v in states.values() if v == "ENFORCED-CONTRADICTED"),
        "WAIVED": sum(1 for v in states.values() if v == "WAIVED"),
        "NA": sum(1 for v in states.values() if v == "NA"),
    }
    live_split = {b: sum(1 for v in subs.values() if v == b) for b in SUB.BUCKETS}
    assert (own, substituted, undeclared) == (
        live_split[SUB.OWN_MECHANISM],
        live_split[SUB.SUBSTITUTED],
        live_split[SUB.UNDECLARED_BUCKET],
    ), (
        f"the published ENFORCED split "
        f"(own={own}, substituted={substituted}, undeclared={undeclared}) "
        f"does not reproduce; the tree says {live_split}")
    assert (waived, na) == (live["WAIVED"], live["NA"]), (
        f"the published WAIVED/NA ({waived}/{na}) does not reproduce; the tree "
        f"says {live['WAIVED']}/{live['NA']}")
    assert contradicted == live["CONTRADICTED"], (
        f"the published CONTRADICTED ({contradicted}) does not reproduce; the "
        f"tree says {live['CONTRADICTED']}")
    assert own + substituted + undeclared == live["ENFORCED"], (
        f"the three ENFORCED columns sum to "
        f"{own + substituted + undeclared}, but {live['ENFORCED']} cells are "
        f"ENFORCED — some cell is in no column or in two")
    # THE ONE THAT WOULD HAVE CAUGHT THE FOLD. Every assertion above compares a
    # published figure to a live figure, so all of them stayed green while the
    # headline said 453 and the row said 481: no single one of them spans both
    # the headline and the row. This does -- the six columns must account for
    # every cell exactly once.
    assert own + substituted + undeclared + contradicted + waived + na == len(states), (
        f"the published columns account for "
        f"{own + substituted + undeclared + contradicted + waived + na} cells "
        f"but the matrix has {len(states)}. A published row that does not "
        f"partition is how a contradicted cell hides inside an enforcement "
        f"figure.")


def test_no_substituted_cell_is_inside_a_figure_presented_as_enforcement():
    """The finding, as an assertion. THIS is the one that fails on the old tree.

    Dimension 8's substituted cells were reported as plain ``ENFORCED`` and the
    README totalled them into one figure. Two properties are required, and the
    old tree had neither:

      * the census must be ABLE to tell the two apart — a suite where every
        ENFORCED cell reads OWN or UNDECLARED has no substitution vocabulary at
        all, which is how 45 cells travelled as enforcement of gates they never
        touched;
      * the published block must show the substituted count in its OWN column,
        never folded into an ENFORCED total.

    The second half is checked by construction: a block whose ENFORCED figure
    is a single number cannot satisfy the five-column total row, and a block
    that prints ``substituted`` as 0 while the tree measures 45 fails the
    equality above.
    """
    subs = CV.substitution_census()
    substituted = {k for k, v in subs.items() if v == SUB.SUBSTITUTED}
    assert substituted, (
        "no cell in the whole 504 reports itself as substituted, yet "
        "dimension 8 replaces every step's declared gate with a stand-in for "
        "45 of its 61 ENFORCED cells (KNOWN GAP #2 in its own docstring). "
        "Either the substitution contract is not wired — in which case those "
        "45 are being published as enforcement of gates they never touch, "
        "which is the defect — or dimension 8 stopped substituting and its "
        "docstring is now wrong."
    )

    block = _block()
    own, substituted_n, undeclared, _, _, _ = _total_row(block)
    assert substituted_n == len(substituted), (
        f"the block publishes {substituted_n} substituted cells; the tree "
        f"measures {len(substituted)}")
    # And the number is not merely present — it must be OUTSIDE the figure a
    # reader would take as enforcement.
    assert f"**{own + substituted_n}**" not in block, (
        f"the block prints **{own + substituted_n}** — own plus substituted "
        f"as one bold figure. That is precisely the fold this contract "
        f"removes: the substituted cells stop being visible the moment they "
        f"are added to the cells that were really measured.")


def test_every_substitution_disclosure_says_what_was_substituted():
    """A bare "substituted" label discloses nothing a reader can act on."""
    mods = CV.dimension_modules()
    seen = 0
    for (sid, dim), buck in CV.substitution_census().items():
        if buck != SUB.SUBSTITUTED:
            continue
        text = SUB.disclosure_for(mods[dim], sid, "ENFORCED")
        assert isinstance(text, str) and not SUB.validate(text), (
            f"d{dim}/{sid}: disclosure not admissible: {SUB.validate(text)}")
        seen += 1
    assert seen, (
        "NOTHING_SCANNED: no substituted cell was examined, so this test "
        "passed without grading a single disclosure")
