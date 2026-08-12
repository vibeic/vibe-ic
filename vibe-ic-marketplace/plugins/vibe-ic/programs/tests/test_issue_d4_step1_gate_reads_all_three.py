#!/usr/bin/env python3
"""Step 1's gate must read all three deliverables it declares — and the any-of
must stay scoped to the two SPELLINGS of one artefact.

`test_d4_gate_measures_what_it_claims[step1]` is the dimension-4 cell this
repairs; these are the properties that make the repair a real one rather than a
green. The one that matters most is `test_the_report_clause_is_NOT_any_of`:
appending the reports to the existing `any_of: true` list would have satisfied
dimension 4 and left the reports unenforced, because one match settles an any-of
clause. A fix that buys a green without buying enforcement is the defect, not the
repair.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parents[2]
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
REPO = PLUGIN.parents[2]

RTL_SPELLINGS = ["phase2/stage1/rtl/*.sv", "phase2/stage1/rtl/*.v"]
REPORTS = ["reports/phase1/extraction_coverage_report.md",
           "reports/phase1/extraction_coverage_report.json"]


def _step1() -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    for s in doc["steps"]:
        if str(s["id"]) == "1":
            return s
    raise AssertionError("step 1 is gone from the flow")


def _clauses(gate: dict) -> list:
    return list(gate.get("all_of") or [])


def test_every_declared_output_is_read_by_some_clause_of_the_gate():
    """The dimension-4 property itself, asserted here in the flow's own terms.

    ALL-of-N across entries, any-of only INSIDE one entry — the same grammar
    `flow_compliance_check` executes, so this cannot drift from the consumer.
    """
    step = _step1()
    declared = list(step["required_outputs"])
    assert len(declared) == 3, f"the declaration moved: {declared}"
    checked = []
    for c in _clauses(step["gate"]):
        checked.extend(c.get("files_exist") or [])
    unread = []
    for entry in declared:
        alts = [a.strip() for a in entry.split(" OR ")]
        if not any(a in checked for a in alts):
            unread.append(entry)
    assert not unread, (
        f"step 1 declares {len(declared)} deliverables and its gate reads "
        f"{checked}; unread: {unread}")


def test_the_report_clause_is_NOT_any_of():
    """THE ONE THAT MAKES THIS A REPAIR AND NOT A GREEN.

    `any_of: true` means ONE match settles the clause. Putting the two reports in
    the same any-of clause as the RTL spellings would satisfy dimension 4 and
    leave the reports unenforced — RTL alone would still pass. Both reports are
    separate deliverables and both must be required.
    """
    clauses = _clauses(_step1()["gate"])
    assert len(clauses) == 2, (
        f"expected two all_of clauses (RTL spellings, then the reports); got "
        f"{len(clauses)}: {clauses}")
    rep = next((c for c in clauses
                if set(c.get("files_exist") or []) == set(REPORTS)), None)
    assert rep is not None, f"no clause requires exactly the two reports: {clauses}"
    assert rep.get("any_of") is not True, (
        "the report clause is any_of, so ONE report satisfies it and the other "
        "is unenforced. The reports are two deliverables, not two spellings of "
        "one.")


def test_PAIRED_the_RTL_clause_KEEPS_its_any_of():
    """The twin. `.sv` and `.v` ARE two spellings of one artefact, and requiring
    both would fail every project that legitimately ships only one."""
    clauses = _clauses(_step1()["gate"])
    rtl = next((c for c in clauses
                if set(c.get("files_exist") or []) == set(RTL_SPELLINGS)), None)
    assert rtl is not None, f"the RTL clause is gone: {clauses}"
    assert rtl.get("any_of") is True, (
        "the RTL clause lost its any_of, so a project shipping only .v (or only "
        ".sv) now fails — that is over-enforcement, not enforcement")


def test_the_gate_is_still_files_exist_only():
    """Step 1's AUDIT NOTE says the gate is presence-only ON PURPOSE: spec->RTL
    is the irreducible AI authoring step and its substance is verified
    downstream. This repair must not smuggle in a substance check."""
    for c in _clauses(_step1()["gate"]):
        assert set(c) <= {"files_exist", "any_of"}, (
            f"a non-files_exist key appeared in step 1's gate: {c}. Wiring "
            f"phase1_coverage_report_present_check is a separate change.")


def test_the_orphan_enforcer_is_still_unwired_and_that_is_STATED():
    """`phase1_coverage_report_present_check` reads the recorded coverage
    percentage and is registered in the P0 umbrella, but no step gate clause
    invokes it. This repair does not wire it; the docstring says so, and this
    fails the day someone wires it so the comment cannot go stale.
    """
    # A MENTION IS NOT A WIRING, and the first version of this test conflated
    # them: it counted occurrences of the program NAME, and the disclosure
    # comment written by this very change mentions it — so the test reported the
    # enforcer as wired and failed on its own documentation. Count gate CLAUSES.
    text = FLOW.read_text()
    doc = yaml.safe_load(text)
    wired = []
    for s in doc["steps"]:
        for c in _walk_clauses(s.get("gate")):
            cmd = c.get("program_exit_zero") or c.get("advisory_program_exit_zero") or ""
            if "phase1_coverage_report_present_check" in str(cmd):
                wired.append(str(s["id"]))
    if wired:
        assert "wired to NO step gate clause" not in text, (
            f"the enforcer is now wired at step(s) {wired} but step 1's comment "
            f"still says it is not; remove the stale disclosure")
    else:
        assert "wired to NO step gate clause" in text, (
            "the enforcer is unwired and the flow does not say so anywhere")


def _walk_clauses(gate):
    """Every clause of a gate, nesting flattened. Empty for a step with no gate."""
    if not isinstance(gate, dict):
        return []
    out = [gate]
    for key in ("all_of", "any_of"):
        v = gate.get(key)
        if isinstance(v, list):
            for sub in v:
                out.extend(_walk_clauses(sub))
    return [c for c in out if isinstance(c, dict)]


# ---------------------------------------------------------------------------
# THE ENFORCEMENT DELTA, pinned so it cannot grow quietly
# ---------------------------------------------------------------------------
def _roots_with_staged_rtl():
    out = set()
    for p in REPO.rglob("phase2/stage1/rtl"):
        if not p.is_dir():
            continue
        try:
            if any(f.suffix in (".v", ".sv") for f in p.iterdir() if f.is_file()):
                out.add(p.parents[2])
        except OSError:
            continue
    return sorted(out)


@pytest.mark.skipif(not (REPO / "benchmark-data").is_dir(),
                    reason="no benchmark-data in this checkout")
def test_the_roots_this_newly_reddens_are_all_EVALUATION_runs():
    """Measured: 8 of 40 roots with staged RTL carry no extraction-coverage
    report, so step 1 now FAILs on them where it passed on the RTL alone.

    Every one is a benchmark EVALUATION run, not an IC cell — CVDP single-module
    tasks and one nested phase1_parity path — and none goes through Phase-1 doc
    extraction, so none ever produced the report. The gate now says so.

    This asserts the CLASS, not the count: a newly-reddened root that is an IC
    cell would be a real regression and must not hide inside a number.
    """
    newly_red = []
    for r in _roots_with_staged_rtl():
        if not all((r / rel).is_file() for rel in REPORTS):
            newly_red.append(r.relative_to(REPO).as_posix())
    assert newly_red, "the probe found nothing; it is broken"
    ic_cells = [r for r in newly_red if r.startswith("benchmark-data/ic/")]
    assert not ic_cells, (
        f"step 1 now fails on published IC cells: {ic_cells}. Those are the "
        f"cells the flow's own results are quoted from; reddening one is a "
        f"regression, not enforcement.")
    for r in newly_red:
        assert r.startswith("benchmark-data/evaluation/"), (
            f"{r} is newly reddened and is neither an IC cell nor an evaluation "
            f"run; the class this repair was measured against has changed")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
