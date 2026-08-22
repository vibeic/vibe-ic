#!/usr/bin/env python3
"""Tests for power_total_vs_budget_check.py — total power must reach a
COMPARISON, or the step must REFUSE and name the budget it lacks.

THIS FILE CARRIES A HALF OF THE PREDICATE THE CORPUS CANNOT PROVE.

`matrix_mutation_ledger.ART-POWER-FIGURES-X1000` records that step 33's cell
STILL cannot be reddened after this gate was wired, and its entry says why that
is correct: 0 of the 17 published runs carrying a power report declares an L19
`power_budget_uw`, so on real data there is nothing to compare against and the
gate refuses. That is an honest record, but on its own it would leave the OTHER
branch — the one that reddens — asserted and never executed, which is the exact
defect the mutation ledger exists to refuse.

`test_the_ledger_mutation_reddens_a_run_that_declares_a_budget` closes that: it
applies the LEDGER'S OWN 1000x exponent shift to a report inside a project whose
L19 does declare a budget, and requires the gate to go red. So the claim "the
mutation would redden a run with a budget" is measured here rather than
promised.

Fixtures are SYNTHETIC and carry no process, foundry or chip token.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PROG = _HERE.parent / "power_total_vs_budget_check.py"
sys.path.insert(0, str(_HERE.parent))

#: The tabular shape a power tool's `report_power` emits: four figures per row
#: and a Total row. Total power here is 3.12e-04 W = 312 uW.
RPT = """\
power analyser 2.7.0 — vectorless
POWER_ANALYSIS_MODE: vectorless_sdc
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             2.75e-04   8.19e-06   5.28e-10   2.83e-04  90.5%
Combinational          1.83e-05   1.13e-05   3.17e-10   2.95e-05   9.5%
Clock                  0.00e+00   0.00e+00   0.00e+00   0.00e+00   0.0%
----------------------------------------------------------------
Total                  2.93e-04   1.95e-05   8.45e-10   3.12e-04 100.0%
"""

#: The ledger's ART-POWER-FIGURES-X1000 edits, verbatim: shift every non-zero
#: exponent three decades and leave the zeros alone, so the table still sums to
#: its own total.
LEDGER_EDITS = (("e-04", "e-01"), ("e-05", "e-02"),
                ("e-06", "e-03"), ("e-10", "e-07"))


def _project(tmp_path: Path, budget, rpt: str = RPT, extra_budgets=()) -> Path:
    proj = tmp_path / "run"
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "power.rpt").write_text(rpt)
    l19dir = proj / "phase1" / "generated_docs"
    l19dir.mkdir(parents=True, exist_ok=True)
    (l19dir / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"doc_id": "L19", "fields": {"pdk_target": "generic",
                                     "power_budget_uw": budget}}))
    for i, b in enumerate(extra_budgets):
        d = proj / "phase1" / f"copy{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
            {"doc_id": "L19", "fields": {"power_budget_uw": b}}))
    return proj


def _run(proj: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(proj), *[str(a) for a in args]],
        capture_output=True, text=True)


# ── the DECISION ───────────────────────────────────────────────────────────
def test_total_over_declared_budget_fails(tmp_path):
    proj = _project(tmp_path, budget=100.0)          # 312 uW vs 100 uW
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "POWER_TOTAL_OVER_BUDGET" in r.stdout
    # Both sides named. A finding that states only the offence cannot be
    # checked by the person reading it.
    assert "3.1200e+02" in r.stdout
    assert "1.0000e+02" in r.stdout


def test_total_under_declared_budget_passes_and_names_the_threshold(tmp_path):
    proj = _project(tmp_path, budget=1000.0)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("[PASS]")
    assert "1.0000e+03 uW" in r.stdout
    assert "L19.power_budget_uw" in r.stdout
    assert "utilization" in r.stdout


def test_the_ledger_mutation_reddens_a_run_that_declares_a_budget(tmp_path):
    """The half the published corpus cannot prove.

    Apply ART-POWER-FIGURES-X1000's own exponent shift to a project whose L19
    DOES declare a budget the true figure meets. Before: 312 uW under a 1000 uW
    budget. After: 312000 uW, which is 312x over. If this ever stops going red,
    the ledger entry's claim that only the missing oracle stands between this
    cell and a red has become false.
    """
    mutated = RPT
    for frm, to in LEDGER_EDITS:
        assert frm in mutated
        mutated = mutated.replace(frm, to)
    clean = _project(tmp_path / "clean", budget=1000.0)
    dirty = _project(tmp_path / "dirty", budget=1000.0, rpt=mutated)
    assert _run(clean).returncode == 0
    r = _run(dirty)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "POWER_TOTAL_OVER_BUDGET" in r.stdout


# ── the REFUSAL, which is what the published corpus actually gets ──────────
def test_absent_budget_refuses_and_names_the_authority(tmp_path):
    proj = _project(tmp_path, budget=None)
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr   # REFUSAL tier, vibe-ic#1017
    assert "[PASS]" not in r.stdout
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "power_budget_uw" in r.stdout
    assert "1 of 1 published copy/copies" in r.stdout


def test_disagreeing_copies_are_not_an_authority(tmp_path):
    """Phase 1 publishes L19 into several directories. If two copies state
    different budgets, taking the first would make the verdict depend on glob
    order — so the budget is treated as undeclared and the disagreement is
    reported."""
    proj = _project(tmp_path, budget=1000.0, extra_budgets=(2000.0,))
    r = _run(proj)
    assert r.returncode == 2          # REFUSAL tier, vibe-ic#1017
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "copies disagree" in r.stdout


def test_agreeing_copies_are_one_authority(tmp_path):
    proj = _project(tmp_path, budget=100.0, extra_budgets=(100.0,))
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "POWER_TOTAL_OVER_BUDGET" in r.stdout


def test_empty_project_refuses_and_discloses(tmp_path):
    """Zero denominator: REFUSE, and refusing means rc 2 (vibe-ic#1017).

    This gate is a BLOCKING `program_exit_zero` clause at step 33, and
    `program_exit_zero` reads the EXIT CODE. Until #1017 an empty tree — no
    power report, no L19 — exited 0 and PASSED that clause while this very
    stdout said the total was NOT compared against anything.
    """
    proj = tmp_path / "empty"
    (proj / "reports").mkdir(parents=True)
    r = _run(proj)
    assert r.returncode == 2
    assert "[PASS]" not in r.stdout
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "read 0 total-power figure(s)" in r.stdout
    assert "a readable Total row" in r.stdout


def test_incomplete_sentinel_survives_the_flow_tail_cut(tmp_path):
    """The consumer keeps only the last `_OUTPUT_SNIPPET_CHARS` characters of
    stdout, so the sentinel has to be near the END. Asserted against the
    consumer's own functions so the two cannot drift apart."""
    import flow_compliance_check as fcc
    proj = _project(tmp_path, budget=None)
    r = _run(proj)
    snippet = fcc.output_snippet(r.stdout, r.stderr)
    assert fcc._stdout_signals_token(snippet, fcc._INCOMPLETE_STDOUT_TOKEN)


def test_budget_override_is_honoured(tmp_path):
    proj = _project(tmp_path, budget=None)
    assert _run(proj, "--budget-uw", "100").returncode == 1
    assert _run(proj, "--budget-uw", "1000").returncode == 0


def test_json_report_carries_the_comparison(tmp_path):
    proj = _project(tmp_path, budget=1000.0)
    out = tmp_path / "out.json"
    assert _run(proj, "--json", str(out)).returncode == 0
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "PASS"
    assert doc["comparison"]["power_budget_uw"] == 1000.0
    assert round(doc["comparison"]["total_power_uw"], 6) == 312.0


def test_bad_argument_is_an_argument_error(tmp_path):
    proj = _project(tmp_path, budget=None)
    assert _run(proj, "--budget-uw", "0").returncode == 2
    assert subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True).returncode == 2


# ── the TIER AS THE CONSUMER SEES IT (vibe-ic#1017) ────────────────────────
def test_the_refusal_reaches_the_flow_as_not_a_pass(tmp_path):
    """The exit code only matters because of what `flow_compliance_check` does
    with it, so assert it THERE and not just here.

    This is the whole of vibe-ic#1017. Both of this campaign's step-25/step-33
    gates printed a refusal and returned 0, and `program_exit_zero` — a
    BLOCKING clause — reads the exit code, not the prose. An empty tree passed.
    `test_matrix_d2_falsifiable::test_d2_gate_has_a_reachable_fail` said so on
    main for five merges and was merged past each time.

    Driven through the consumer's own wrapper rather than a re-implementation
    of its rules, so it cannot drift from them: rc 2 must land in the
    VACUOUS_PASS tier — the "input-missing skip convention", explicitly NOT a
    clean result — and a real comparison must still land in PASS.
    """
    import flow_compliance_check as fcc

    empty = tmp_path / "empty"
    (empty / "reports").mkdir(parents=True)
    ok, out = fcc._check_program_exit_zero(
        empty, "power_total_vs_budget_check .")
    assert ok, out            # rc 2 is not a FAIL ...
    assert out.startswith(fcc._VACUOUS_HINT_PREFIX), out   # ... and not a PASS

    real = _project(tmp_path / "real", budget=1000.0)
    ok2, out2 = fcc._check_program_exit_zero(real, "power_total_vs_budget_check .")
    assert ok2, out2
    assert not out2.startswith(fcc._VACUOUS_HINT_PREFIX), out2
