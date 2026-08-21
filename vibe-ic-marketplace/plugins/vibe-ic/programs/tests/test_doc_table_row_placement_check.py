"""`doc_table_row_placement_check` must refuse a table row that is not in a table.

`plugin_version_prose_sync_check` asks whether a version claim AGREES with the
shipped one. A claim inserted in the WRONG PLACE still agrees, so that gate is
structurally unable to see this: one release inserted a two-row version-and-count
fragment five times into running prose, each time replacing the sentence that was
there, and twenty-five subsequent bumps faithfully advanced the number inside the
spurious rows.

The rule is the DELIMITER row, not the neighbours: in GitHub-Flavoured Markdown a
run of pipe lines with no row of dashes is not a table and never renders as one.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "doc_table_row_placement_check.py"
#: .../<repo>/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/<this file>
REPO_ROOT = Path(__file__).resolve().parents[5]

RC_PASS, RC_FAIL, RC_VACUOUS, RC_USAGE = 0, 1, 2, 3

REAL_TABLE = (
    "Some prose above it.\n"
    "\n"
    "| Plugin version | 1.2.3 |\n"
    "|---|---|\n"
    "| Programs | 1232 |\n"
    "\n"
    "Some prose below it.\n"
)

SWALLOWED = (
    "The gate runs on every landing and refuses a stale manifest.\n"
    "| Plugin version | 1.2.3 |\n"
    "| Programs | 1232 |\n"
    "Callers read the exit code, never the prose.\n"
)


def _doc(tmp_path: Path, text: str, name: str = "d.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=600)


# ── the honest case ──────────────────────────────────────────────────────────

def test_a_real_table_passes(tmp_path):
    r = _run(_doc(tmp_path, REAL_TABLE))
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "3 table-shaped line(s)" in r.stdout, \
        "the reach is not stated:\n" + r.stdout


def test_the_shipped_corpus_is_clean(tmp_path):
    """The guard must be green on the tree it ships in, or it is a bug rather
    than a gate. This is the corpus sweep, pinned."""
    assert (REPO_ROOT / ".git").exists(), f"{REPO_ROOT} is not the repository root"
    r = _run("--repo", REPO_ROOT)
    assert r.returncode == RC_PASS, r.stdout + r.stderr


# ── the defect ───────────────────────────────────────────────────────────────

def test_a_fragment_pasted_into_prose_is_refused(tmp_path):
    ok = _run(_doc(tmp_path, REAL_TABLE, "good.md"))
    assert ok.returncode == RC_PASS, "control arm is not green:\n" + ok.stdout

    r = _run(_doc(tmp_path, SWALLOWED, "bad.md"))
    assert r.returncode == RC_FAIL, "a swallowed sentence passed:\n" + r.stdout
    assert "bad.md" in r.stdout and "delimiter row" in r.stdout, r.stdout


def test_the_finding_carries_the_prose_it_displaced(tmp_path):
    """The neighbours are the evidence — they are the halves of the sentence the
    paste replaced, and a reader who cannot see them cannot repair the file."""
    r = _run(_doc(tmp_path, SWALLOWED, "bad.md"), "--json", tmp_path / "r.json")
    doc = json.loads((tmp_path / "r.json").read_text())
    assert len(doc["findings"]) == 1, doc
    f = doc["findings"][0]
    assert f["before"].startswith("The gate runs"), f
    assert f["after"].startswith("Callers read"), f


def test_a_pipe_table_inside_a_fence_is_not_a_finding(tmp_path):
    """Inside a fenced block everything is literal, so an EXAMPLE table drawn
    without a delimiter is not a claim about anything. Fences are what keep the
    corpus sweep at zero false positives."""
    text = ("Example:\n\n```\n| a | b |\n| 1 | 2 |\n```\n\nEnd.\n")
    r = _run(_doc(tmp_path, text))
    assert r.returncode == RC_PASS, r.stdout


def test_a_single_dash_delimiter_is_a_real_table(tmp_path):
    """`|-|-|-|` is legal GFM. Demanding two dashes produced this program's
    first false positive, on a vendored upstream document."""
    text = "| Regression | Version |\n|-|-|\n| a | 1.1.0 |\n"
    r = _run(_doc(tmp_path, text))
    assert r.returncode == RC_PASS, r.stdout


# ── the vacuous tier ─────────────────────────────────────────────────────────

def test_examining_no_document_is_vacuous_and_says_so(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty)
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "NOT a pass" in r.stdout, r.stdout


# ── the bad invocation tier ──────────────────────────────────────────────────

def test_a_path_that_does_not_exist_is_rc3_not_rc2(tmp_path):
    r = _run(tmp_path / "no-such.md")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_an_unknown_flag_is_rc3_not_argparse_2(tmp_path):
    r = _run("--not-a-flag")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


# ── discrimination: revert the rule, the refusal disappears ──────────────────

def test_reverting_the_delimiter_rule_lets_the_fragment_pass(tmp_path):
    """THE MUTATION ARM. `orphan_blocks` only reports a run of rows with NO
    delimiter; make it report none, and the swallowed sentence — refused above —
    passes."""
    bad = _doc(tmp_path, SWALLOWED, "bad.md")
    honest = _run(bad)
    assert honest.returncode == RC_FAIL, "control arm is not red:\n" + honest.stdout

    source = PROG.read_text(encoding="utf-8")
    mutant_body = source.replace(
        "        if not any(DELIMITER.fullmatch(b.strip()) for b in block):",
        "        if False:")
    assert mutant_body != source, "the mutation did not apply — the rule moved"
    mutant = tmp_path / "mutant.py"
    mutant.write_text(mutant_body, encoding="utf-8")

    import os
    r = subprocess.run(
        [sys.executable, str(mutant), str(bad)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": str(PROG.parent)})
    assert r.returncode == RC_PASS, (
        "the mutant still refused, so the refusal does not come from the "
        "delimiter rule:\n" + r.stdout + r.stderr)
