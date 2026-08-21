"""vibe-ic#1052 — the corpus census must be able to SEE a verdict move.

Every test drives the REAL tool over REAL throwaway trees and REAL clause
programs, for the reason `test_corpus_write_guard.py` gives about
`_gate_dispatch.sh`: a fixture copy of the logic drifts from the code that runs.

THE PAIRED GUARD IS THE POINT OF THIS FILE. A census that never reads the green
arm reports `MOVED 0` over every corpus in existence and looks exactly like a
change with no impact. `test_a_census_that_ignored_the_green_arm_would_die_here`
is the control that separates the two: same red tree, two different green trees,
and the answers must differ. Delete the green read and it goes red.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[5]
_TOOL = _REPO / "tools" / "vacuous_exit_corpus_census.py"
_PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
_T = 55


def _tree(root: Path, clause_rc: dict, runs=("ic/alpha", "ic/beta")) -> Path:
    """A throwaway repo: some published run dirs, and clauses with fixed rc."""
    for r in runs:
        (root / "benchmark-data" / r / "reports").mkdir(parents=True, exist_ok=True)
    progs = root / _PLUGIN_REL / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for name, rc in clause_rc.items():
        (progs / f"{name}.py").write_text(
            "import sys\n"
            f"print('{name}: fixture')\n"
            f"sys.exit({rc})\n", encoding="utf-8")
    return root


def _run(*args):
    return subprocess.run([sys.executable, str(_TOOL), *args],
                          capture_output=True, text=True, timeout=_T)


def test_a_moved_verdict_is_counted_and_its_transition_named(tmp_path):
    red = _tree(tmp_path / "red", {"c1": 0})
    green = _tree(tmp_path / "green", {"c1": 2})
    p = _run("--red", str(red), "--green", str(green), "--clause", "c1")
    assert p.returncode == 0, p.stderr
    assert "verdict MOVED : 2" in p.stdout, p.stdout
    assert "rc 0 -> rc 2 : 2 pair(s)" in p.stdout, p.stdout
    assert "at least one moved verdict: 2 of 2" in p.stdout, p.stdout


def test_an_unchanged_clause_moves_nothing(tmp_path):
    red = _tree(tmp_path / "red", {"c1": 0})
    green = _tree(tmp_path / "green", {"c1": 0})
    p = _run("--red", str(red), "--green", str(green), "--clause", "c1")
    assert p.returncode == 0, p.stderr
    assert "verdict MOVED : 0" in p.stdout, p.stdout
    assert "verdict SAME  : 2" in p.stdout, p.stdout


def test_a_census_that_ignored_the_green_arm_would_die_here(tmp_path):
    """THE PAIRED GUARD.

    One red tree, two greens that differ only in the rc their clause returns.
    A census reading only the red arm cannot tell these apart and returns the
    same `MOVED` for both — so this is the single assertion in the file that a
    green-blind implementation cannot satisfy, and it is why the two cases above
    are not enough on their own.
    """
    red = _tree(tmp_path / "red", {"c1": 0})
    same = _tree(tmp_path / "g_same", {"c1": 0})
    diff = _tree(tmp_path / "g_diff", {"c1": 2})

    a = _run("--red", str(red), "--green", str(same), "--clause", "c1")
    b = _run("--red", str(red), "--green", str(diff), "--clause", "c1")
    assert a.returncode == 0 and b.returncode == 0, (a.stderr, b.stderr)

    moved_a = [l for l in a.stdout.splitlines() if "verdict MOVED" in l][0]
    moved_b = [l for l in b.stdout.splitlines() if "verdict MOVED" in l][0]
    assert moved_a != moved_b, (
        "the census gave the SAME answer for two different green arms, so it is "
        "not reading the green arm at all — every future landing would be told "
        "its change moves nothing.\n"
        f"same-green: {moved_a}\ndiff-green: {moved_b}")
    assert "MOVED : 0" in moved_a and "MOVED : 2" in moved_b


def test_an_empty_corpus_refuses_rather_than_reporting_zero_moved(tmp_path):
    """`0 moved` and `nothing to ask` are opposite facts, not one exit code."""
    red = tmp_path / "red"
    (red / _PLUGIN_REL / "programs").mkdir(parents=True)
    (red / _PLUGIN_REL / "programs" / "c1.py").write_text("import sys\nsys.exit(0)\n")
    green = _tree(tmp_path / "green", {"c1": 2}, runs=())
    p = _run("--red", str(red), "--green", str(green), "--clause", "c1")
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "NOT_MEASURED" in p.stderr, p.stderr
    assert "MOVED" not in p.stdout


def test_no_clause_set_refuses_instead_of_guessing_one(tmp_path):
    red = _tree(tmp_path / "red", {"c1": 0})
    green = _tree(tmp_path / "green", {"c1": 2})
    p = _run("--red", str(red), "--green", str(green))
    assert p.returncode == 2, (p.returncode, p.stdout)
    assert "NOT_MEASURED" in p.stderr, p.stderr


def test_a_clause_that_cannot_be_run_is_named_not_folded_into_SAME(tmp_path):
    """An unrunnable clause must never read as 'this run did not move'."""
    red = _tree(tmp_path / "red", {"c1": 0})
    green = _tree(tmp_path / "green", {"c1": 2})
    p = _run("--red", str(red), "--green", str(green),
             "--clause", "c1", "--clause", "does_not_exist")
    assert p.returncode == 0, p.stderr
    assert "NOT MEASURED  : 2" in p.stdout, p.stdout
    assert "[NOT MEASURED] does_not_exist" in p.stdout, p.stdout
    assert "verdict SAME  : 0" in p.stdout, p.stdout


def test_the_clause_set_is_printed_so_a_verdict_cannot_read_wider(tmp_path):
    red = _tree(tmp_path / "red", {"c1": 0, "c2": 0})
    green = _tree(tmp_path / "green", {"c1": 2, "c2": 0})
    p = _run("--red", str(red), "--green", str(green), "--clause", "c1")
    assert p.returncode == 0, p.stderr
    assert "clause set under census (1): c1" in p.stdout, p.stdout
    assert "c2" not in p.stdout.split("clause set under census")[1].split("\n")[0]
