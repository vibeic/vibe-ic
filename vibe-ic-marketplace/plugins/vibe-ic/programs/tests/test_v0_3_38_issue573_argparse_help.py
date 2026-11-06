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









# ── the live sweep: the shipped programs/ tree must stay clean ──────────────
