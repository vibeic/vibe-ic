"""Rule 6 — a changed repo-root ``tools/`` script selects the tests that drive it.

THE MEASURED HOLE (vibe-ic#1057). `tools/gatekeeper-land.sh` is named by 38
test files. A change to it selected 15 — the smoke floor, and nothing else. The
selection was byte-identical whether the change was a one-character comment or
a rewrite of the landing script, so it said nothing about the file that moved.

Two independent causes, either one sufficient on its own, so both are pinned
below by a separate test:

  * `select_tests` skipped every changed path not ending in ``.py``, so a shell
    script never reached a rule at all; and
  * even ``tools/foo.py`` failed ``rp.parent.as_posix() in _SOURCE_DIRS``,
    because a repo-root path is not plugin-relative.

The repo ships no ``.github/workflows/`` (only ``workflows-disabled/``), so this
selection IS the gate — there is no broader job behind it that would have caught
the miss. That is why the floor being "green" was worth nothing here.

Motivating case, from the field: v1.10.32 changed `tools/gatekeeper-land.sh`,
and under the pre-fix selector that change would not have selected a single one
of its own tests.

Every expectation below is DERIVED FROM THE TREE — the truth set is recomputed
by scanning `programs/tests/` for the name. Nothing here hardcodes a list of
test filenames, which would rot the first time a script is added or renamed.
"""
from __future__ import annotations

from pathlib import Path

import ci_targeted_test_select as sel

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent   # …/vibe-ic
PLUGIN_PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"
TESTS_REL = "programs/tests"
MOTIVATING = "gatekeeper-land.sh"


def _select(changed, root=PLUGIN_ROOT, prefix=PLUGIN_PREFIX):
    return set(sel.select_tests(list(changed), root, plugin_prefix=prefix,
                                mode=sel.MODE_IMPORT_EDGE))


def _tests_naming(basename: str, root: Path = PLUGIN_ROOT) -> set[str]:
    """The truth set, recomputed from the tree — never a hardcoded list."""
    pat = sel._tool_ref_pattern(basename)
    out = set()
    for tf in (root / TESTS_REL).glob("test_*.py"):
        if pat.search(tf.read_text(encoding="utf-8", errors="replace")):
            out.add(f"{TESTS_REL}/{tf.name}")
    return out


def test_the_motivating_case_selects_every_test_that_names_the_script():
    """`tools/gatekeeper-land.sh` — the v1.10.32 file — reaches its tests."""
    truth = _tests_naming(MOTIVATING)
    assert len(truth) > 20, (
        "premise moved: this script is no longer widely referenced, so it is "
        f"no longer the motivating case ({len(truth)} test files name it)")
    out = _select([f"tools/{MOTIVATING}"])
    missing = truth - out
    assert not missing, f"named but not selected: {sorted(missing)}"


def test_the_selection_is_strictly_more_than_the_floor():
    """The defect in one line: the change contributed NOTHING over smoke.

    Fails against the pre-fix selector, which returned exactly the floor — this
    is the assertion that makes the fix load-bearing rather than decorative.
    """
    floor = set(sel._smoke_set(PLUGIN_ROOT))
    out = _select([f"tools/{MOTIVATING}"])
    assert out > floor, (
        "a repo-root tools/ change selected only the smoke floor — the "
        "selection says nothing about the file that changed")
    assert len(out - floor) > 20


def test_a_shell_script_reaches_a_rule_at_all():
    """Cause 1: the `.py` guard. A `.sh` must not be dropped before any rule."""
    assert _select([f"tools/{MOTIVATING}"]) > set(sel._smoke_set(PLUGIN_ROOT))


def test_a_repo_root_python_tool_is_not_treated_as_a_plugin_source():
    """Cause 2: `tools/*.py` is outside `_SOURCE_DIRS`, so ownership misses it.

    `gen_programs_index.py` is driven BY PATH from the hygiene tests; the rule
    must reach them through the reference edge, not through `_SOURCE_DIRS`.
    """
    truth = _tests_naming("gen_programs_index.py")
    assert truth, "premise moved: no test names gen_programs_index.py"
    assert truth <= _select(["tools/gen_programs_index.py"])


# ── negative controls: the rule must be able to select NOTHING ──────────────
#
# A rule that widens every selection is indistinguishable from deleting the
# selector. These pin that it fires only on a real, matching edge.

def test_an_unreferenced_tool_contributes_nothing():
    """A tool no test names selects exactly the floor — no blanket widening.

    The probe name is ASSEMBLED at runtime so the joined literal never appears
    in this file. Spelling it out made this test select ITSELF and fail — the
    rule was right and the fixture was wrong, which is worth keeping as a note:
    a test that names a tool really is a consumer of it.
    """
    floor = set(sel._smoke_set(PLUGIN_ROOT))
    probe = "unreferenced" + "_probe_" + "xyzzy" + ".sh"
    assert probe not in Path(__file__).read_text(encoding="utf-8"), \
        "the probe leaked into this file's text; it would match itself"
    assert _select([f"tools/{probe}"]) == floor


def test_a_non_tool_path_outside_the_plugin_is_untouched():
    """`docs/` is not a tool dir; rule 6 must not fire on it."""
    floor = set(sel._smoke_set(PLUGIN_ROOT))
    assert _select(["docs/some_note.md"]) == floor


def test_a_suffix_name_does_not_inherit_the_longer_script_s_tests(tmp_path):
    """Boundary: `land.sh` must not match inside `pre-land.sh`.

    Whole-token matching is what keeps a newly added script from silently
    inheriting an existing one's tests — a selection that looks richer while
    pointing at code that did not change.
    """
    tests = tmp_path / TESTS_REL
    tests.mkdir(parents=True)
    (tests / "test_only_names_the_long_one.py").write_text(
        'CMD = "tools/pre-land.sh"\n', encoding="utf-8")

    only_long = _select(["tools/pre-land.sh"], root=tmp_path, prefix="")
    only_short = _select(["tools/land.sh"], root=tmp_path, prefix="")

    target = f"{TESTS_REL}/test_only_names_the_long_one.py"
    assert target in only_long, "the exact name must match"
    assert target not in only_short, (
        "`land.sh` matched inside `pre-land.sh` — substring matching would "
        "hand an unrelated script another script's tests")


def test_the_rule_reads_a_directory_not_a_filename_list(tmp_path):
    """A tool added TODAY is covered without editing the selector.

    The rule is keyed on the `tools/` DIRECTORY, so a brand-new script that no
    release has ever seen still resolves. A hardcoded filename list would fail
    this the moment someone adds a script.
    """
    tests = tmp_path / TESTS_REL
    tests.mkdir(parents=True)
    (tests / "test_drives_a_brand_new_script.py").write_text(
        'run("tools/freshly_invented_tool.sh")\n', encoding="utf-8")
    out = _select(["tools/freshly_invented_tool.sh"], root=tmp_path, prefix="")
    assert f"{TESTS_REL}/test_drives_a_brand_new_script.py" in out
