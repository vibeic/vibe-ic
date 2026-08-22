"""vibe-ic#707 — a skip whose verdict word is COMPUTED was invisible.

`gate_skip_routing_check` reads a skip out of the leading STRING LITERAL of a
`print`. When the verdict is interpolated —

    label = "NOT CHECKED" if verdict == "SKIP" else verdict
    print(f"[{label}] some_check ...")
    ...
    if verdict == "SKIP":
        return 2

— the leading literal is `"["`, which carries no token. The scanner reported
neither a skip nor an uncertainty, so those modules never entered the ratchet's
population and the published `98 == 98` balance was computed over a set that
structurally excluded them. Measured on origin/main: `skip_paths=0
unresolved=0` for all four analog-hil gates, each of which plainly has one.

Same shape as #693 one level down: scope became coverage.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_skip_routing_check as G  # noqa: E402


def _scan(src: str):
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return G.scan_skip_paths(fn)


_REAL_SHAPE = '''
def main():
    verdict = report["verdict"]
    label = "NOT CHECKED" if verdict == "SKIP" else verdict
    print(f"[{label}] some_check (cap={n})")
    for b in blocks:
        print(f"  [{b}] detail")
    if verdict == "SKIP":
        return 2
    return 0
'''


def test_a_computed_verdict_with_a_skip_return_is_UNRESOLVED():
    """The whole point: not a skip, not a non-skip — an answer the scanner
    cannot give, and it must be counted as such."""
    _skips, unresolved = _scan(_REAL_SHAPE)
    assert len(unresolved) == 1, (
        "an interpolated verdict beside a skip-tier return must be recorded as "
        "unresolved, not silently read as 'no skip here'")


def test_a_literal_verdict_is_still_resolved_normally():
    """The fix must not turn readable announcements into uncertainty."""
    src = '''
def main():
    if not path.is_file():
        print("SKIP: nothing to read")
        return 2
    return 0
'''
    skips, unresolved = _scan(src)
    assert skips and not unresolved


def test_an_interpolated_print_with_NO_skip_return_is_not_counted():
    """The narrowing that keeps the tally a disclosure. Counting every
    interpolated print took the tree-wide unanalysable count from 9 to 311,
    which is noise. Both halves must be present."""
    src = '''
def main():
    print(f"processed {n} file(s)")
    return 0
'''
    _skips, unresolved = _scan(src)
    assert not unresolved


def test_a_leading_word_before_the_interpolation_is_a_real_literal():
    """`print(f"SKIP: {why}")` HAS a readable verdict — only punctuation may
    precede the interpolation for the word to count as computed."""
    src = '''
def main():
    print(f"SKIP: {why}")
    return 2
'''
    skips, unresolved = _scan(src)
    assert skips and not unresolved


def test_the_four_gates_named_in_the_issue_now_disclose_theirs():
    """Measured on the real modules, not a fixture."""
    for m in ("analog_hil_iteration_cap_check", "analog_hil_report_schema_check",
              "analog_hil_single_knob_check", "analog_hw_tb_de10lite_budget_check"):
        p = PROGRAMS / f"{m}.py"
        if not p.is_file():
            continue
        tree = ast.parse(p.read_text())
        total = 0
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += len(G.scan_skip_paths(n)[1])
        assert total >= 1, f"{m} still reports no uncertainty at all"
