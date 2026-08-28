"""A red earned on an empty tree is not evidence the gate can fail.

Measured on the 68x9 matrix (mutation probe, plugin v1.12.33): 54 of the 121
reds dimension D2 counted as falsifiability were earned on an EMPTY project,
where the FAIL text is `REQUIRED_ARTEFACT_MISSING` / `MISSING_NETLIST` /
"no file on disk matches pattern". Killing a gate's namesake verdict while
leaving its absence arm alive left D2 green.

Both arms are asserted at the same denominator: the classifier must SEE the
difference the dimension could not.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import gate_red_is_more_than_absence_census as G

_PROGRAMS = Path(G.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]

_ABSENCE_ARM = (
    "from pathlib import Path\n"
    "def main(p):\n"
    "    if not Path(p).exists():\n"
    "        print('REQUIRED_ARTEFACT_MISSING: no clock plan on disk')\n"
    "        return 1\n"
)
_VERDICT_ARM = (
    "    if not doc['clocks']:\n"
    "        print('CLOCK_PLAN_EMPTY: the plan declares zero clocks')\n"
    "        return 1\n"
    "    return 0\n"
)


def test_a_gate_with_both_arms_is_verdict_bearing():
    assert G.classify_source(_ABSENCE_ARM + _VERDICT_ARM)["kind"] == "VERDICT-BEARING"


def test_the_measured_mutation_flips_the_classification():
    """M2: kill the namesake verdict, leave the absence arm alive."""
    before = G.classify_source(_ABSENCE_ARM + _VERDICT_ARM)
    after = G.classify_source(_ABSENCE_ARM + "    return 0\n")
    assert before["kind"] == "VERDICT-BEARING"
    assert after["kind"] == "ABSENCE-ONLY"
    assert after["absence_reds"] == 1 and after["verdict_reds"] == 0


def test_a_real_verdict_bearing_gate_flips_when_its_content_arm_goes():
    """The same mutation, on a module this repo actually ships."""
    rows = {p.name: G.classify_source(p.read_text(encoding="utf-8", errors="ignore"))
            for p in G.gate_files(_ROOT)}
    bearing = [n for n, r in rows.items() if r["kind"] == "VERDICT-BEARING"]
    assert bearing, "no VERDICT-BEARING gate in the corpus to mutate"
    victim = _PROGRAMS / sorted(bearing)[0]
    text = victim.read_text(encoding="utf-8", errors="ignore")
    line = G.classify_source(text)["first_verdict_line"]
    lines = text.splitlines()
    # remove the verdict red itself — the design's own failure arm
    del lines[line - 1]
    after = G.classify_source("\n".join(lines))
    assert after["verdict_reds"] < rows[victim.name]["verdict_reds"], (
        victim.name, rows[victim.name], after)


def test_an_unparseable_module_is_unanalysable_not_clean():
    assert G.classify_source("def main(:\n")["kind"] == "UNANALYSABLE"


def test_a_computed_exit_is_named_undecidable_not_clean():
    """`return rc` says nothing about the KIND of red — do not fold it in."""
    src = "def main():\n    rc = judge()\n    return rc\n"
    assert G.classify_source(src)["kind"] == "NO-LITERAL-RED"


def test_the_census_runs_and_reports_its_denominator():
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_red_is_more_than_absence_census.py"),
         "--root", str(_ROOT), "--json"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    import json
    data = json.loads(out.stdout)
    assert data["scanned"] > 100
    assert sum(data["counts"].values()) == data["scanned"]


# ------------------------------------------------------- the wired mode -----
def test_the_self_test_passes_on_a_two_sided_population():
    rows = {"a_check.py": G.classify_source(_ABSENCE_ARM + _VERDICT_ARM),
            "b_check.py": G.classify_source(_ABSENCE_ARM + "    return 0\n")}
    assert G.self_test(rows) == 0


def test_the_self_test_refuses_a_one_sided_population():
    """A census over a set that exercises one side of its predicate is not a pass."""
    rows = {"b_check.py": G.classify_source(_ABSENCE_ARM + "    return 0\n")}
    assert G.self_test(rows) == 2


# ─────────────────────────────────────────────────────────────────────────────
# THE REAL MUTATION. MEASURED 2026-08-29: killing the content arm of
# `floorplan_pdn_check` — `return 1 if fail else 0` -> `return 0` — moved
# NOTHING in this census. Two independent causes, both fixed and both pinned
# below.
# ─────────────────────────────────────────────────────────────────────────────
def test_a_red_returned_by_a_conditional_expression_is_seen():
    """`return 1 if fail else 0` is an ast.IfExp, not a Constant."""
    import ast
    fn = ast.parse("def f(fail):\n    return 1 if fail else 0\n").body[0]
    assert G._is_red(fn.body[0]), (
        "the commonest way a gate returns its verdict was invisible to this census")


def test_that_shape_is_common_enough_to_matter():
    """Not a one-gate accident: it is how many gates end their main()."""
    import ast
    from pathlib import Path
    hits = 0
    for path in G.gate_files(_ROOT):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.IfExp):
                if any(v in (1, 3) for v in G._red_constants(node.value)):
                    hits += 1
                    break
    assert hits >= 10, (
        f"only {hits} gates use `return <red> if ... else 0`; if that is now "
        f"rare this test should be re-argued, but while it is common the "
        f"census must read it")


def test_an_upper_snake_absence_id_is_not_counted_as_a_verdict_red():
    """`FLOORPLAN_DEF_UNPARSEABLE` was the ONLY red credited as that gate's
    verdict arm. It is an unreadable-input red — absence by this file's own
    vocabulary — and it escaped because `\\bunparse` finds no word boundary
    after an underscore."""
    assert G.ABSENCE_RE.search("FLOORPLAN_DEF_UNPARSEABLE: could not read")
    assert G.ABSENCE_RE.search("PDN_STRIPES_MISSING: none found")
    # ...but a genuine content verdict must NOT be swept in with them
    assert not G.ABSENCE_RE.search("CLOCK_PLAN_EMPTY: the plan declares zero clocks")


def test_the_real_gate_is_classified_honestly_now():
    """floorplan_pdn_check can only fail on an input it could not read."""
    from pathlib import Path
    src = (_PROGRAMS / "floorplan_pdn_check.py")
    if not src.is_file():                                   # pragma: no cover
        import pytest
        pytest.skip("floorplan_pdn_check.py is not in this tree")
    kind = G.classify_source(src.read_text(encoding="utf-8"))["kind"]
    assert kind == "ABSENCE-ONLY", (
        f"expected the census to report this gate as absence-only; got {kind}. "
        f"Before 2026-08-29 it said VERDICT-BEARING on the strength of an "
        f"UNPARSEABLE red.")
