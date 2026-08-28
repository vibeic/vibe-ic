"""ORGANIC #573 — phase1 docs-runner --help crashed with
`ValueError: incomplete format`: the `--strict` flag's help text ended with
a bare `%` ("coverage < 80%.") and argparse percent-expands every help
string.  Fixes: (a) escape as `80%%` in phase1_doc_one_shot_runner.py;
(b) new argparse_help_format_check.py pins the whole defect class
(bare `%` in any add_argument help string under a tree).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import argparse_help_format_check as AH  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── the named defect artifact: phase1 docs runner --help must work ──────────

def test_phase1_doc_runner_help_exits_zero():
    result = _pr.run(
        [sys.executable, str(PROG / "phase1_doc_one_shot_runner.py"), "--help"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "incomplete format" not in result.stderr
    assert "--strict" in result.stdout


# ── the class pin: static checker semantics ─────────────────────────────────

def test_checker_flags_bare_percent_help(tmp_path):
    """The issue's exact shape: help text ending `< 80%.` must FAIL."""
    (tmp_path / "bad.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--strict', action='store_true',\n"
        "               help='Exit 1 on TODO stubs OR coverage < 80%.')\n"
    )
    rc = AH.main([str(tmp_path)])
    assert rc == 1


def test_checker_passes_escaped_and_expansion_forms(tmp_path):
    (tmp_path / "good.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--strict', help='coverage < 80%% required')\n"
        "p.add_argument('--tol', default=1.0, type=float,\n"
        "               help='tolerance (default %(default)s)')\n"
    )
    rc = AH.main([str(tmp_path)])
    assert rc == 0


def test_checker_flags_bare_percent_in_fstring_literal_part(tmp_path):
    (tmp_path / "fbad.py").write_text(
        "import argparse\n"
        "X = 5\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--t', help=f'max delta % (default {X})')\n"
    )
    rc = AH.main([str(tmp_path)])
    assert rc == 1


def test_checker_flags_trailing_percent(tmp_path):
    (tmp_path / "tail.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--c', help='coverage %')\n"
    )
    rc = AH.main([str(tmp_path)])
    assert rc == 1


# ── the live sweep: the shipped programs/ tree must stay clean ──────────────

def test_programs_tree_has_no_bare_percent_help():
    violations = AH.audit(str(PROG))
    assert violations == [], "\n".join(violations)
