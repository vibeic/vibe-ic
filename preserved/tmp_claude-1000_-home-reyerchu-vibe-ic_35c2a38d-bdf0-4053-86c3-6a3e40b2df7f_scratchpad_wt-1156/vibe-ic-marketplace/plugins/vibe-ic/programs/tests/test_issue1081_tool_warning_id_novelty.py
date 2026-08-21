"""vibe-ic#1081 — a tool diagnostic id that was not there last time BLOCKS.

Adopted from OpenROAD-flow-scripts @ f9ec54a6. ORFS counts warnings by message
id and reports an unseen one (`flow/util/checkMetadata.py:91-95`), but
`flow/util/genRuleFile.py:70-75` assigns `level: warning`, so a brand-new tool
warning never fails their build.

WHY MAKING IT BLOCKING IS SAFE, and why these tests can exist at all: the check
never asks *"is this warning acceptable"* — that needs an oracle. It asks *"did
this id exist last time"*, decidable from two runs of the same cell. §D9.

THE FIXTURES USE REAL IDS. `DRT-0349`, `ODB-0220`, `DRT-0036` are message ids
measured in this repo's own tracked logs, not invented shapes — so a regex that
stopped matching real OpenROAD output would fail here rather than pass on a
convenient fiction.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import tool_warning_id_novelty_check as N  # noqa: E402

GATE = _PROGRAMS / "tool_warning_id_novelty_check.py"

#: Two WARNINGs and one INFO. The INFO must never be counted.
HONEST_LOG = ("[INFO DRT-0036] made 12 nets\n"
              "[WARNING DRT-0349] antenna violation on net foo\n"
              "[WARNING ODB-0220] pin has no placement\n")


def _run(*args):
    p = subprocess.run([sys.executable, str(GATE), *map(str, args)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


@pytest.fixture
def cell(tmp_path):
    """A run tree with a recorded baseline — i.e. 'last time' exists."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "pnr.log").write_text(HONEST_LOG)
    rc, out = _run(run, "--write-baseline")
    assert rc == N.RC_PASS, out
    return run


def _accept(tmp_path, *entries):
    p = tmp_path / "accept.json"
    p.write_text(json.dumps({"accepted": list(entries)}))
    return p


# ── the property: novelty, decided without an oracle ────────────────────────

def test_an_unchanged_run_passes(cell):
    rc, out = _run(cell)
    assert rc == N.RC_PASS, out


def test_a_new_diagnostic_id_is_BLOCKING(cell):
    """The deliverable. ORFS only WARNs here; we fail."""
    (cell / "pnr.log").write_text(HONEST_LOG + "[WARNING RSZ-0062] new\n")
    rc, out = _run(cell)
    assert rc == N.RC_FAIL, out
    assert "NEW DIAGNOSTIC RSZ-0062" in out, out
    assert "BLOCKING" in out, out


def test_a_new_ERROR_id_is_also_blocking(cell):
    (cell / "pnr.log").write_text(HONEST_LOG + "[ERROR ORD-0012] boom\n")
    rc, out = _run(cell)
    assert rc == N.RC_FAIL, out
    assert "ORD-0012" in out, out


def test_INFO_ids_are_not_counted(cell):
    """Measured exclusion, not taste: the corpus carries 26x [INFO DRT-0036]
    and similar progress chatter whose ids churn with every tool build."""
    (cell / "pnr.log").write_text(HONEST_LOG + "[INFO RCX-0442] extracted\n")
    rc, out = _run(cell)
    assert rc == N.RC_PASS, f"an INFO id was treated as a diagnostic:\n{out}"


def test_a_disappearing_id_is_not_a_failure(cell):
    """Only NOVELTY blocks. A warning that stopped appearing is an improvement
    and must not redden — asserting otherwise would make the check unusable."""
    (cell / "pnr.log").write_text("[WARNING DRT-0349] antenna\n")
    rc, out = _run(cell)
    assert rc == N.RC_PASS, out


# ── the acceptance list, and it expires ─────────────────────────────────────

def test_an_accepted_id_passes(cell, tmp_path):
    (cell / "pnr.log").write_text(HONEST_LOG + "[WARNING RSZ-0062] new\n")
    acc = _accept(tmp_path, {"id": "RSZ-0062", "accepted_on": "2026-08-12",
                             "reason": "resizer advisory, adjudicated in #1081"})
    rc, out = _run(cell, "--accept", acc)
    assert rc == N.RC_PASS, out


def test_an_undated_or_unreasoned_acceptance_is_refused(cell, tmp_path):
    """An acceptance nobody dated or explained is indistinguishable from
    someone silencing a diagnostic they never looked at."""
    (cell / "pnr.log").write_text(HONEST_LOG + "[WARNING RSZ-0062] new\n")
    for bad in ({"id": "RSZ-0062"},
                {"id": "RSZ-0062", "accepted_on": "2026-08-12", "reason": "  "}):
        acc = _accept(tmp_path, bad)
        rc, out = _run(cell, "--accept", acc)
        assert rc == N.RC_FAIL, f"{bad} was accepted:\n{out}"
        assert "MALFORMED ACCEPTANCE" in out, out


def test_a_stale_acceptance_expires_loudly(cell, tmp_path):
    """#1081: 'the acceptance list must itself be checked, so a stale entry
    expires loudly rather than accumulating'."""
    acc = _accept(tmp_path, {"id": "XXX-9999", "accepted_on": "2026-01-01",
                             "reason": "long gone"})
    rc, out = _run(cell, "--accept", acc)
    assert rc == N.RC_FAIL, out
    assert "STALE ACCEPTANCE XXX-9999" in out, out


# ── vacuity: never a silent pass ────────────────────────────────────────────

def test_no_baseline_is_vacuous_not_a_pass(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "pnr.log").write_text(HONEST_LOG)
    rc, out = _run(run)
    assert rc == N.RC_VACUOUS, out
    assert "NOT a pass" in out, out


def test_no_diagnostics_at_all_is_vacuous(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "pnr.log").write_text("nothing interesting here\n")
    rc, out = _run(run)
    assert rc == N.RC_VACUOUS, out
    assert "nothing was compared" in out, out


# ── the regex is anchored to REAL tool output ───────────────────────────────

def test_the_id_pattern_matches_real_tracked_logs():
    """If the pattern drifted from what OpenROAD actually prints, every test
    above would pass over fixtures while seeing nothing in the corpus."""
    repo = _PROGRAMS.parents[3]
    logs = list((repo / "benchmark-data").rglob("*.log"))
    if not logs:
        pytest.skip("no tracked logs in this checkout")
    hits = set()
    for p in logs[:40]:
        try:
            hits |= {m for _s, m in
                     N.DIAG_RE.findall(p.read_text(errors="replace"))}
        except OSError:
            continue
    assert hits, ("the pattern matched no WARNING/ERROR id in any tracked log — "
                  "it has drifted from real tool output and the fixtures above "
                  "are proving nothing about real runs")


# ── paired guard ────────────────────────────────────────────────────────────

def test_a_scanner_that_finds_nothing_is_killed(cell, monkeypatch):
    """An always-empty scan would make every tier above pass vacuously."""
    (cell / "pnr.log").write_text(HONEST_LOG + "[WARNING RSZ-0062] new\n")
    real = N.audit(cell, cell / N.BASELINE_NAME, None)
    assert real["verdict"] == "FAIL", real

    monkeypatch.setattr(N, "scan_ids", lambda _root: {})
    blind = N.audit(cell, cell / N.BASELINE_NAME, None)
    assert blind["verdict"] == "VACUOUS", blind
    assert blind["verdict"] != real["verdict"], (
        "a scanner that finds nothing is indistinguishable from a clean run, "
        "so these tests would not notice the scan being broken")
