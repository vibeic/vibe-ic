#!/usr/bin/env python3
"""The refusal-remedy census, proven to discriminate rather than to count.

A census that always answers the same thing is a number, not a measurement.
So every property below is asserted in the direction that could fail:

  1. POSITIVE   a refusal that really does name its remedy is scored as naming
                one -- and the one used is a REAL site in this repository, not
                a fixture authored beside this test.
  2. MUTATION   remove the remedy sentence from that same message and the
                census must move, AND MOVE ONLY THERE. A census whose count
                changes by more than the thing mutated is measuring something
                else.
  3. REACHABILITY  a guard that cannot reach its own refusing verdict is not a
                guard. `--strict` must return 1 on a tree with a silent
                refusal and 0 on a tree without one. Both branches are driven.

WHY THE POPULATION IS NOT KEYED ON A NAME, pinned here so a later reader does
not "simplify" it into a prefix match: measured on this tree, `[REFUSED]` is
printed at 11 sites while the bracketed-token print population is 1058 sites
across 104 tokens. `test_the_population_is_shape_derived_not_name_derived`
asserts the census finds builder names it was never told about.

chip-AGNOSTIC: no vendor, foundry, process node, SKU or design name.
"""
import ast
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import refusal_names_its_remedy_census as C   # noqa: E402

PLUGIN = PROGRAMS.parent
FLOW = (PLUGIN / "flow/phase1_phase2_phase3.yaml")

#: The real refusal this census was written out of. It is the one site in the
#: repository that names a path, a key AND a flag, which is why it is the
#: positive control: nothing else can be carrying the assertion for it.
_SUBJECT_FILE = "submission_template_check.py"
_SUBJECT_RULE = "NO_TEMPLATE_WITHOUT_REASON"


@pytest.fixture(scope="module")
def live():
    text = FLOW.read_text(encoding="utf-8", errors="replace") if FLOW.is_file() else ""
    sites, examined = C.scan_programs(PROGRAMS, text, PLUGIN)
    return sites, examined


@pytest.fixture()
def scratch():
    root = Path(tempfile.mkdtemp(prefix="remedy_census_"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _site(sites, file, rule):
    hits = [s for s in sites if s["file"] == file and s["rule"] == rule]
    assert hits, f"{file}::{rule} is not in the population at all"
    return hits


# --------------------------------------------------------------------------- #
# 1. POSITIVE — a real refusal that names its remedy
# --------------------------------------------------------------------------- #
def test_positive_a_refusal_that_names_its_remedy_is_scored_as_naming_one(live):
    sites, _ = live
    hits = _site(sites, _SUBJECT_FILE, _SUBJECT_RULE)
    assert len(hits) == 1, hits
    s = hits[0]
    assert s["names_path"] and s["names_key"] and s["names_flag"], s
    assert s["wide"] and s["strict"], s


def test_the_message_is_rendered_through_its_constants_not_grepped(live):
    """The remedy is named through `ST.DESIGN_ANSWERS_REL`, not a literal.

    A source-text grep would score this refusal SILENT — the well-behaved one —
    which is the failure mode that would have made the whole census backwards.
    """
    src = (PROGRAMS / _SUBJECT_FILE).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and len(n.args) >= 2
                and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == _SUBJECT_RULE):
            found = n
    assert found is not None
    literal = "".join(p.value for p in found.args[1].values
                      if isinstance(p, ast.Constant) and isinstance(p.value, str)) \
        if isinstance(found.args[1], ast.JoinedStr) else ""
    assert "input/step_0_5ic_answers.json" not in literal, (
        "the subject must name its path through a CONSTANT, or this test is "
        "not exercising the renderer")

    consts, alias = C._module_constants(PROGRAMS)
    rendered = "".join(C.render(a, Path(_SUBJECT_FILE).stem, consts, alias)
                       for a in found.args[1:])
    assert "input/step_0_5ic_answers.json" in rendered, rendered[:400]


def test_the_population_is_shape_derived_not_name_derived(live):
    """The census finds builders it was never told the names of."""
    sites, examined = live
    builders = {s["builder"] for s in sites}
    assert examined["refusal_sites"] > 0 and examined["files_parsed"] > 0
    # none of these appears as a target anywhere in the census's source
    # LOGIC ONLY — the docstring is stripped first. The census QUOTES several
    # of these names as evidence that the shape found them, which is the point
    # of the file; what must not happen is the LOGIC matching on a name. This
    # is the same strict-logic reading `source_chip_agnostic_check` already
    # distinguishes from whole-file.
    mod = ast.parse((PROGRAMS / "refusal_names_its_remedy_census.py")
                    .read_text(encoding="utf-8"))
    if (mod.body and isinstance(mod.body[0], ast.Expr)
            and isinstance(mod.body[0].value, ast.Constant)):
        mod.body = mod.body[1:]
    logic = ast.dump(mod)
    discovered = {b for b in builders if b and b not in C._NOT_BUILDERS}
    assert len(discovered) >= 5, sorted(discovered)
    for b in discovered:
        assert f"'{b}'" not in logic, (
            f"{b} is matched by the census's own LOGIC — the population would "
            f"then be name-derived, which is the defect this file pins")


# --------------------------------------------------------------------------- #
# 2. MUTATION — remove the remedy, and ONLY that site may move
# --------------------------------------------------------------------------- #
def test_mutation_removing_the_remedy_makes_that_one_refusal_silent(live, scratch):
    """And nothing else in the population changes.

    Compared as a per-site NAME SET keyed on (file, line, rule), never as a
    total: two counts that happen to match can hide a two-in/two-out swap.
    """
    before_sites, before = live
    subject = _site(before_sites, _SUBJECT_FILE, _SUBJECT_RULE)[0]

    mirror = scratch / "programs"
    shutil.copytree(PROGRAMS, mirror,
                    ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"))
    victim = mirror / _SUBJECT_FILE
    src = victim.read_text(encoding="utf-8")
    # excise exactly the disclosure sentences this change added
    start = src.index('f" WHERE THE REASON IS SUPPLIED:')
    end = src.index('f"{read}{extra}"', start)
    mutated = src[:start] + src[end:]
    mutated = mutated.replace('f"{read}{extra}"', 'f"{extra}"')
    assert mutated != src
    victim.write_text(mutated, encoding="utf-8")

    text = FLOW.read_text(encoding="utf-8", errors="replace")
    after_sites, after = C.scan_programs(mirror, text, PLUGIN)

    def key(s):
        return (s["file"], s["rule"], s["wide"], s["strict"])
    b = sorted(key(s) for s in before_sites)
    a = sorted(key(s) for s in after_sites)
    moved = sorted(set(b) ^ set(a))
    assert [m[:2] for m in moved] == [(_SUBJECT_FILE, _SUBJECT_RULE)] * len(moved), moved
    assert moved, "the mutation changed nothing — the census cannot see its subject"

    now = _site(after_sites, _SUBJECT_FILE, _SUBJECT_RULE)[0]
    assert not now["wide"] and not now["strict"], now
    assert after["silent_wide"] == before["silent_wide"] + 1, (
        before["silent_wide"], after["silent_wide"])
    assert subject["wide"] is True


# --------------------------------------------------------------------------- #
# 3. REACHABILITY — the refusing branch is reachable, and the passing one too
# --------------------------------------------------------------------------- #
_NAMED = '''\
REPORT_REL = "reports/phase1/example.json"


def _f(rule, message, **extra):
    return {"rule": rule, "message": message}


def check():
    out = []
    out.append(_f("A_SILENT_LOOKING_RULE",
                  f"nothing here is checkable. Supply it at {REPORT_REL}."))
    return out
'''

_SILENT = '''\
def _f(rule, message, **extra):
    return {"rule": rule, "message": message}


def check():
    out = []
    out.append(_f("A_RULE_THAT_NAMES_NOTHING",
                  "this refusal tells the reader nothing they could act on"))
    return out
'''


def test_reachability_strict_reaches_both_of_its_own_verdicts(scratch):
    """A guard that cannot reach its refusing branch only ever says yes."""
    clean = scratch / "clean"
    clean.mkdir()
    (clean / "a_named.py").write_text(_NAMED, encoding="utf-8")
    rc_clean = C.main(["--programs", str(clean), "--strict"])

    dirty = scratch / "dirty"
    dirty.mkdir()
    (dirty / "a_named.py").write_text(_NAMED, encoding="utf-8")
    (dirty / "b_silent.py").write_text(_SILENT, encoding="utf-8")
    rc_dirty = C.main(["--programs", str(dirty), "--strict"])

    assert (rc_clean, rc_dirty) == (0, 1), (rc_clean, rc_dirty)

    sites, ex = C.scan_programs(dirty)
    assert ex["refusal_sites"] == 2, sites
    assert ex["silent_wide"] == 1, ex
    # and the named one was named by a CONSTANT it resolved, not a literal
    named = [s for s in sites if s["rule"] == "A_SILENT_LOOKING_RULE"][0]
    assert named["names_path"], named


def test_an_empty_scan_is_undetermined_not_clean(scratch):
    empty = scratch / "empty"
    empty.mkdir()
    assert C.main(["--programs", str(empty)]) == 2
    assert C.main(["--programs", str(scratch / "nope")]) == 2


def test_the_census_exits_zero_without_strict_and_says_it_is_a_census(live, capsys):
    """It reports debt; it must not block. And it must SAY which it is."""
    rc = C.main([str(PLUGIN)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[CENSUS]" in out, out
    doc = C.__doc__ or ""
    assert doc[:4000].find("ENFORCEMENT:") >= 0, "declaration outside the 4 kB window"
    assert "CENSUS, not a gate" in doc[:4000]


def test_both_figures_are_reported_and_neither_is_alone(live):
    """WIDE and STRICT are both published; one number would hide that PATH is
    the loosest detector."""
    _, e = live
    assert e["names_remedy_wide"] >= e["names_remedy_strict"]
    assert set(e["by_detector"]) == {"path", "key", "flag"}
    assert e["silent_wide"] + e["names_remedy_wide"] == e["refusal_sites"]
    assert e["silent_strict"] + e["names_remedy_strict"] == e["refusal_sites"]
    assert "floor on the defect" in e["population_shape"]
