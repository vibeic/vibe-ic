"""`generated_test_list_min_guard` must refuse a generated test list on a
MINIMUM, never on emptiness.

Two measured failures, 2026-08-21, one day apart in the same harness. They read
the same — green — and they fail in opposite directions:

    an EMPTY list runs EVERY test   (pytest falls back to `testpaths`)
    a list naming a MISSING path runs ZERO and reports success

`tools/gatekeeper-land.sh` tests `[ ! -s "$sel" ]`, which sees the first only in
its extreme form and cannot see the second at all.

Every arm is asserted in both directions, and the final test reverts the rule
and watches the refusal disappear.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "generated_test_list_min_guard.py"

RC_PASS, RC_FAIL, RC_VACUOUS, RC_USAGE = 0, 1, 2, 3


def _root(tmp_path: Path, names) -> Path:
    root = tmp_path / "root"
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# a test file\n", encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _list(tmp_path: Path, lines, name: str = "sel.txt") -> Path:
    p = tmp_path / name
    p.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return p


def _run(*args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True)


NAMES = [f"tests/test_{i}.py" for i in range(5)]


# ── the honest case ──────────────────────────────────────────────────────────

def test_a_list_at_or_above_its_floor_with_every_path_present_passes(tmp_path):
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, NAMES), "--min", 5, "--root", root)
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "5 distinct" in r.stdout, "the reach is not stated:\n" + r.stdout


# ── failure one: too few, INCLUDING the non-empty kind ───────────────────────

def test_an_empty_list_is_refused(tmp_path):
    """The list that makes a runner collect the WHOLE suite."""
    root = _root(tmp_path, NAMES)
    ok = _run(_list(tmp_path, NAMES), "--min", 5, "--root", root)
    assert ok.returncode == RC_PASS, "control arm is not green:\n" + ok.stdout

    r = _run(_list(tmp_path, [], "empty.txt"), "--min", 5, "--root", root)
    assert r.returncode == RC_FAIL, r.stdout


def test_a_non_empty_list_far_below_its_floor_is_refused(tmp_path):
    """THE POINT OF THE PROGRAM. Three entries where the caller declared the
    selection worth 900 is the same class of wrong as zero, and `[ ! -s ]`
    passes it."""
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, NAMES[:3]), "--min", 5, "--root", root)
    assert r.returncode == RC_FAIL, "a shrunken selection passed:\n" + r.stdout
    assert "3 distinct" in r.stdout and "minimum of 5" in r.stdout, r.stdout


def test_duplicates_cannot_inflate_a_list_over_its_floor(tmp_path):
    """A minimum written over LINE COUNT is satisfied by one path repeated. The
    floor is compared against DISTINCT entries, and the duplication is named."""
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, [NAMES[0]] * 5), "--min", 5, "--root", root)
    assert r.returncode == RC_FAIL, "a list of one path repeated passed:\n" + r.stdout
    assert "1 distinct" in r.stdout, r.stdout
    assert "duplicated" in r.stdout, r.stdout


# ── failure two: a path that does not exist ──────────────────────────────────

def test_one_unresolvable_path_refuses_the_whole_list(tmp_path):
    """Measured: one non-existent path among five produced a zero-test run
    reported as success."""
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, NAMES + ["tests/test_gone.py"]),
             "--min", 5, "--root", root)
    assert r.returncode == RC_FAIL, r.stdout
    assert "tests/test_gone.py" in r.stdout, \
        "the unresolvable path is not named:\n" + r.stdout


def test_the_json_report_carries_the_counts_and_the_missing_paths(tmp_path):
    root = _root(tmp_path, NAMES)
    out = tmp_path / "r.json"
    _run(_list(tmp_path, NAMES + ["tests/test_gone.py"]),
         "--min", 5, "--root", root, "--json", out)
    doc = json.loads(out.read_text())
    assert doc["distinct"] == 6 and doc["minimum"] == 5, doc
    assert doc["missing"] == ["tests/test_gone.py"], doc


# ── the vacuous tier ─────────────────────────────────────────────────────────

def test_an_unreadable_root_is_vacuous_and_says_so(tmp_path):
    """rc 2 with the marker: whether the entries exist could not be DECIDED, so
    nothing was verified. It must not become a pass."""
    r = _run(_list(tmp_path, NAMES), "--min", 5, "--root", tmp_path / "nope")
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "NOT a pass" in r.stdout, r.stdout


# ── the bad invocation tier ──────────────────────────────────────────────────

def test_a_missing_minimum_is_rc3_not_argparse_2(tmp_path):
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, NAMES), "--root", root)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_a_floor_of_zero_is_rejected_as_a_command_line(tmp_path):
    """`--min 0` is a request to accept the failure this program exists for, so
    it is refused as a bad invocation rather than honoured."""
    root = _root(tmp_path, NAMES)
    r = _run(_list(tmp_path, NAMES), "--min", 0, "--root", root)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "not a floor" in r.stderr, r.stderr


def test_an_unreadable_list_is_rc3(tmp_path):
    root = _root(tmp_path, NAMES)
    r = _run(tmp_path / "no-such-list.txt", "--min", 5, "--root", root)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


# ── discrimination: revert the rule, the refusal disappears ──────────────────

def test_reverting_the_minimum_to_an_emptiness_test_lets_the_shrunken_list_pass(tmp_path):
    """THE MUTATION ARM. Replace the minimum comparison with the emptiness test
    the shell script already had. The three-entry list — refused above — passes,
    which is the whole difference between the two rules stated as an experiment.
    """
    root = _root(tmp_path, NAMES)
    sel = _list(tmp_path, NAMES[:3])
    honest = _run(sel, "--min", 5, "--root", root)
    assert honest.returncode == RC_FAIL, "control arm is not red:\n" + honest.stdout

    source = PROG.read_text(encoding="utf-8")
    mutant_body = source.replace(
        "    if len(distinct) < args.minimum:",
        "    if not distinct:")
    assert mutant_body != source, "the mutation did not apply — the rule moved"
    mutant = tmp_path / "mutant.py"
    mutant.write_text(mutant_body, encoding="utf-8")

    import os
    r = _pr.run(
        [sys.executable, str(mutant), str(sel), "--min", "5", "--root", str(root)],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(PROG.parent)})
    assert r.returncode == RC_PASS, (
        "the mutant still refused, so the refusal does not come from the "
        "minimum:\n" + r.stdout + r.stderr)
