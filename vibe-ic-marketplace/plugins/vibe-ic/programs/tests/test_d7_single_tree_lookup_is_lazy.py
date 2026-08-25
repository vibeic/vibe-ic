"""A single-tree lookup must not parse the whole program tree.

`matrix_d7_artifact_graph._trees()` parses EVERY `programs/*.py`. Measured on
`ab5a23a28`: 1165 files, ~37-46 s of `builtins.compile` in one call.

Three of its callers wanted ONE named tree — `program_literals`,
`_local_modules`, `flag_value_is_written` — and each paid for 1164 parses it
never read. That was not merely wasteful. `flag_value_is_written` is on the
path

    na_precondition -> matrix_cell_state -> cell_states()

so the parse landed inside `test_the_gate_itself_reddens_on_a_grown_flow`,
which shells out under `_PYTEST_TIMEOUT_S = 60`. That bound CANNOT be raised:
the harness ceiling is `180 // 3`, and `ci_harness_timeout_ceiling_check` is
BLOCKING. So the test was red with no legal re-bound available. Measured, on
clean main and on this branch, same tree:

    cell_states() cold      148.90 s  ->  0.31 s
    the nested nodeid       123.65 s  ->  3.53 s
    the growth control      TimeoutExpired after 60 s  ->  1 passed

WHY THESE ASSERTIONS AND NOT A STOPWATCH
----------------------------------------
The obvious guard is "assert it finishes in under N seconds". That guard is
worthless here and would be actively harmful. This fleet's hosts run heavily
oversubscribed — measured at load average 141 on 32 cores while this was being
written, with two readings of the SAME sweep differing 3x (120.75 s vs
41.08 s) from contention alone. A timing assertion would encode that
contention as a constant and would flap on exactly the hosts that are busy.

So the property pinned here is STRUCTURAL and host-independent: how much work
is done, counted, not how long it took.
"""
from __future__ import annotations

import ast
from pathlib import Path

import matrix.flowref as F
import matrix_d7_artifact_graph as G
import test_matrix_d7_outputs_list_complete as D7

#: Measured on ab5a23a28: the full 63-step sweep parses exactly 2 programs.
#: The ceiling is deliberately far above that — this is a "did somebody
#: reintroduce a whole-tree parse" tripwire, not a golden number that has to
#: be re-blessed every time the flow grows a step.
_MAX_PROGRAMS_PARSED = 32


def test_the_cell_state_sweep_never_triggers_the_whole_tree_parse():
    """`_trees()` must not be reached from the `matrix_cell_state` path."""
    G._tree.cache_clear()
    G._trees.cache_clear()
    for sid in F.step_ids():
        D7.matrix_cell_state(sid)
    info = G._trees.cache_info()
    assert info.misses + info.hits == 0, (
        f"`_trees()` was called {info.misses + info.hits} time(s) while "
        f"deciding cell state for {len(list(F.step_ids()))} steps. It parses "
        f"every one of {len(list(F.PROGRAMS_DIR.glob('*.py')))} programs, and "
        f"this path runs inside a 60 s inner bound that cannot be raised — the "
        f"harness ceiling is 180 // 3. Use `_tree(name)` for a single lookup.")


def test_the_cell_state_sweep_parses_only_the_programs_it_reads():
    """Laziness must be real — not the same parse spelled one file at a time."""
    G._tree.cache_clear()
    G._trees.cache_clear()
    for sid in F.step_ids():
        D7.matrix_cell_state(sid)
    parsed = G._tree.cache_info().misses
    total = len(list(F.PROGRAMS_DIR.glob("*.py")))
    assert parsed <= _MAX_PROGRAMS_PARSED, (
        f"the sweep parsed {parsed} of {total} programs (measured: 2). "
        f"Parsing them one at a time costs what parsing them all at once cost; "
        f"the point of `_tree` is that this path reads almost none of them.")


def test_tree_is_exactly_the_whole_tree_lookup_it_replaced():
    """`_tree(x)` must agree with a fresh parse, INCLUDING on absence.

    Checked against `ast.parse` of the file directly rather than against
    `_trees()`, which is now built from `_tree` and so cannot disagree with it.
    """
    names = sorted(p.stem for p in F.PROGRAMS_DIR.glob("*.py"))
    assert len(names) > 500, (
        f"only {len(names)} programs found — this guard is measuring an empty "
        f"population, which proves nothing")

    # A deterministic spread, plus the wrapper family `_local_modules` walks.
    sample = names[::97] + [n for n in ("em_report_check", "signoff_report_check")
                            if n in names]
    checked = 0
    for name in sample:
        src = (F.PROGRAMS_DIR / f"{name}.py").read_text(
            encoding="utf-8", errors="replace")
        try:
            expected = ast.dump(ast.parse(src))
        except SyntaxError:
            assert G._tree(name) is None, (
                f"{name} does not parse, so `_tree` must return None")
            continue
        got = G._tree(name)
        assert got is not None and ast.dump(got) == expected, (
            f"`_tree({name!r})` does not match a fresh parse of the file")
        checked += 1
    assert checked >= 5, f"only {checked} programs actually compared"


def test_tree_returns_none_for_everything_that_is_not_a_program():
    """The three ways `_trees().get()` returned None must still return None.

    A lazy lookup that builds a path from its argument is exactly where a
    directory-traversal or a dotted-module name starts resolving to something
    the dict form never would.
    """
    for absent in ("", "does_not_exist_at_all", "../../etc/passwd",
                   "sub/module", "a.b", "matrix"):
        assert G._tree(absent) is None, (
            f"`_tree({absent!r})` resolved to a tree; the dict lookup it "
            f"replaced returned None for it")

    # `matrix` is a real DIRECTORY under programs/tests — never a program.
    assert not (F.PROGRAMS_DIR / "matrix.py").is_file()
