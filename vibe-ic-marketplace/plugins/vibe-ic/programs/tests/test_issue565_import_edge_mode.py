"""#565 — targeted selection mapped changed modules by FILENAME, not dependency.

`2a632bcfe` changed 734 lines of `phase3_one_shot_runner.py` and removed all 11
lines of the IHP OpenRCX captable discovery landed hours earlier. The four tests
that pin it live in `test_spm_ihp_openrcx_captable_layout.py`, which
`import phase3_one_shot_runner` directly. `ownership` keys on the test FILENAME,
selected none of them, and the revert survived three releases.

MEASURED on that exact changed path, driving the real selector:

    ownership          16 files    misses it
    reference-capped   16 files    misses it TOO
    reference         255 files    catches it, on a lexical mention
    import-edge       175 files    catches it, on a stated dependency

`reference-capped` is the row worth keeping. It looked like the affordable
middle option and gives ZERO protection here, because the cap drops a stem's
entire contribution once more than `ref_max_tests` files name it — and
`phase3_one_shot_runner` is named by 198. The cap zeroes exactly the large,
frequently-changed modules where a silent revert is most likely.

TWO EDGE KINDS, because either alone is a hole. Measured over 2081 test files:

    import edges                    1866
    explicit-loader edges              83   (`spec_from_file_location("<stem>")`)
    source modules the loader edges reach that imports do not   62

An `ast`-only scan misses those 83 — which is this mode's own failure shape one
level down, so both are collected.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

import ci_targeted_test_select as C  # noqa: E402

#: The change that opened this issue.
_CHANGED = ["programs/phase3_one_shot_runner.py"]
#: A test that imports it and is NOT named after it.
_ORPHAN_TEST = "test_spm_ihp_openrcx_captable_layout.py"


def _select(mode):
    return C.select_tests(_CHANGED, _PLUGIN, mode=mode)


def _catches_orphan(mode):
    return any(_ORPHAN_TEST in s for s in _select(mode))


# ── the defect and the fix ───────────────────────────────────────────────────
def test_import_edge_catches_a_test_not_named_after_the_module():
    assert _catches_orphan(C.MODE_IMPORT_EDGE), (
        f"{_ORPHAN_TEST} imports the changed module and was not selected — the "
        f"exact miss that let a silent revert survive three releases")


def test_ownership_still_misses_it():
    """Pins WHY the mode was added. If ownership ever catches it, this file's
    reason has changed and the numbers above need re-measuring rather than the
    test being deleted."""
    assert not _catches_orphan(C.MODE_OWNERSHIP)


def test_reference_capped_misses_it_too():
    """The row that decides against the cheap middle option.

    `reference-capped` looked like the affordable compromise. Its cap zeroes a
    stem named by more than `ref_max_tests` files, and the largest modules are
    exactly where the risk is, so on this class of defect it protects nothing.
    """
    assert not _catches_orphan(C.MODE_REFERENCE_CAPPED)


def test_import_edge_is_cheaper_than_reference():
    """Both catch it; the point is that a stated dependency is a tighter
    relation than a lexical mention, so this is not a strictly-worse trade."""
    n_edge = len(_select(C.MODE_IMPORT_EDGE))
    n_ref = len(_select(C.MODE_REFERENCE))
    assert n_edge < n_ref, (n_edge, n_ref)


# ── the default lane must not move ───────────────────────────────────────────
def test_the_default_is_unchanged():
    """`ownership` is what CI runs. Adding a mode must not widen it — that
    would be a cost change smuggled in as a feature."""
    assert C.select_tests(_CHANGED, _PLUGIN) == _select(C.MODE_OWNERSHIP)


def test_an_unknown_mode_still_raises():
    with pytest.raises(ValueError):
        C.select_tests(_CHANGED, _PLUGIN, mode="no-such-mode")


# ── both edge kinds are collected ────────────────────────────────────────────
def test_the_loader_edge_kind_contributes():
    """`spec_from_file_location("<stem>", …)` is how 62 modules are reached by
    tests that never `import` them. An ast-only index misses those, which is
    this mode's own failure shape one level down.
    """
    stems = C._source_stems(_PLUGIN)
    full = C._build_import_edge_index(_PLUGIN, stems)

    imports_only: dict[str, set] = {}
    for tp in sorted((_PROGRAMS / "tests").rglob("test_*.py")):
        try:
            text = tp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = tp.relative_to(_PLUGIN).as_posix()
        for n in (C._imported_module_names(text, C._own_package(rel)) or set()):
            if n in stems:
                imports_only.setdefault(n, set()).add(rel)

    total_full = sum(len(v) for v in full.values())
    total_imp = sum(len(v) for v in imports_only.values())
    assert total_full > total_imp, (
        "the loader edges contribute nothing; either the pattern stopped "
        "matching or the tree stopped using explicit loaders — both are worth "
        "knowing, and neither should be silent")


def test_the_index_fails_open_on_an_unreadable_test(tmp_path):
    """A selector that dies on one bad file selects nothing, and selecting
    nothing is the defect this mode exists to prevent."""
    fake = tmp_path / "programs" / "tests"
    fake.mkdir(parents=True)
    (tmp_path / "programs" / "some_module.py").write_text("x = 1\n")
    (fake / "test_broken.py").write_text("def f(:\n", encoding="utf-8")
    (fake / "test_ok.py").write_text("import some_module\n", encoding="utf-8")
    idx = C._build_import_edge_index(tmp_path, {"some_module"})
    assert "some_module" in idx, "a syntactically broken sibling emptied the index"
    assert any("test_ok.py" in p for p in idx["some_module"])
