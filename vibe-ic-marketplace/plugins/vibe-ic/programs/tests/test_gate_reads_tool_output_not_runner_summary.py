#!/usr/bin/env python3
"""A gate's number must come from the TOOL, not from a summary of the tool.

TWO GATES, ONE DEFECT, both recorded in `matrix_mutation_ledger.
ARTEFACT_MUTATIONS` as cells that could NOT be reddened from the content of the
artefact they audit:

  ART-ROUTER-FINAL-ITERATION (step 21)  rewrite the router's FINAL detailed-route
      iteration from 0 violations to 12 and leave the runner's summary line at
      the top of the SAME FILE alone -> the gate's verdict did not move, and its
      own stdout still read `real_violation_total=0` while the router's last
      word in the file it had just parsed read 12.

  ART-NETLIST-PRIMITIVE-SWAP (step 9)   substitute `$_AND_` for `$_NAND_` at all
      221 instantiation sites -> the gate's verdict did not move, and its own
      report ENUMERATED `$_AND_` in `cell_type_counts` while passing.

The pair that makes the first one sharp is ART-DRC-ROUTER-SUMMARY: the SAME gate
on the SAME file DOES redden when the SUMMARY is edited. So step 21's green was
a statement about the runner's arithmetic, not about the router's result — and
anyone who edited only the summary was invisible. `test_summary_edit_still_
reddens` is here to make sure closing the tool-output path did not buy it by
breaking the summary path.

EVERY TEST BELOW IS PAIRED. A test that only asserts the red proves the code is
new, not that it bites, so each red case has a green counterpart with the same
fixture and one byte of difference, and the two "not corroborated" cases assert
that the new check DISCLOSES rather than refuses — the failure mode a blanket
"must corroborate" rule would have, which this repo has measured and reverted
before (`gate_zero_denominator_refuses_check`: forcing refusal on four gates
flipped 182 of 182 tracked run dirs).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
DRC_GATE = PROGRAMS / "drc_report_check.py"
NETLIST_GATE = PROGRAMS / "synth_netlist_check.py"


def _run(prog: Path, args: list, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog)] + args,
                          capture_output=True, text=True, cwd=cwd)


# ══════════════════════════════════════════════════════════════════════
# Fixtures — the runner's projection of a router log, and a synth netlist.
# Synthetic, and deliberately carrying no design / PDK / process token.
# ══════════════════════════════════════════════════════════════════════
def _router_report(summary_count: int, iteration_counts) -> str:
    """A router DRC report in the shape this corpus publishes it.

    A RUNNER-written summary block at the top, then the TOOL's own transcript
    below it — including the per-iteration tally that falls as the router
    converges. `iteration_counts=None` produces a report with NO router grammar
    at all (a foundry-deck-style report), which must be UNCORROBORATED rather
    than failed.
    """
    head = (
        "# detailed_route DRC summary -- emitted by the runner\n"
        "# Tool: openroad detailed_route (drt)\n"
        "#\n"
        "openroad / drt-pass: detailed_route invoked\n"
        f"violation report: {summary_count}\n"
        f"violation count summary: {summary_count} violation(s) found\n"
        "drc source: final [INFO DRT-0199] count\n"
        f"DRC clean: {'YES' if summary_count == 0 else 'NO'}\n"
        "tool: openroad\n\n"
        "# === transcript ===\n"
    )
    body = ""
    if iteration_counts is not None:
        for i, n in enumerate(iteration_counts):
            body += (f"[INFO DRT-0195] Start {i}th optimization iteration.\n"
                     f"[INFO DRT-0199]   Number of violations = {n}.\n"
                     f"[INFO DRT-0267] cpu time = 00:00:0{i}, memory = 1.0 (MB)\n"
                     "Total wire length = 1000 um.\n")
    # Pad past the anti-stub byte floor with real transcript-shaped filler so
    # the fixture is rejected for its CONTENT if it is ever rejected at all.
    body += "".join(f"[INFO DRT-0036] layer region query size = {i}.\n"
                    for i in range(200))
    return head + body


def _netlist(primitive: str, n: int = 12) -> str:
    """A yosys `write_verilog -noexpr` netlist instantiating one primitive."""
    body = "module top(a, b, y);\n  input a;\n  input b;\n  output y;\n"
    body += "".join(f"  wire _{i:03d}_;\n" for i in range(n))
    for i in range(n):
        body += (f"  \\{primitive}  _c{i:03d}_ (\n    .A(a),\n    .B(b),\n"
                 f"    .Y(_{i:03d}_)\n  );\n")
    return body + "  assign y = _000_;\nendmodule\n"


def _drc_project(tmp_path, report_text: str) -> Path:
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "drc_router.rpt").write_text(report_text)
    return proj


def _drc(proj: Path):
    """(rc, audit payload) for the router-DRC gate as step 21 wires it."""
    r = _run(DRC_GATE, [".", "--mode", "drc",
                        "--under", "reports/phase3/drc_router.rpt",
                        "--json", "reports/phase3/drc_router.json"], cwd=proj)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:                                   # pragma: no cover
        raise AssertionError(f"gate emitted no audit JSON:\n{r.stdout}\n{r.stderr}")


def _netlist_project(tmp_path, audited: str, tool: str | None) -> Path:
    synth = tmp_path / "proj" / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(audited)
    if tool is not None:
        (synth / "netlist_yosys.v").write_text(tool)
    return tmp_path / "proj"


def _netlist_gate(proj: Path):
    r = _run(NETLIST_GATE, ["--netlist", "phase2/stage2/synth/netlist.v",
                            "--json", "reports/phase2/synth_netlist.json"],
             cwd=proj)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:                                   # pragma: no cover
        raise AssertionError(f"gate emitted no report:\n{r.stdout}\n{r.stderr}")


# ══════════════════════════════════════════════════════════════════════
# Step 21 — the router's own final word
# ══════════════════════════════════════════════════════════════════════
def test_tool_final_iteration_reddens_though_summary_says_clean(tmp_path):
    """ART-ROUTER-FINAL-ITERATION. The router finishes with 12 unresolved
    violations; the summary above it still says 0. This is the cell the ledger
    recorded as CANNOT_REDDEN."""
    proj = _drc_project(tmp_path, _router_report(0, [101, 11, 3, 12]))
    rc, payload = _drc(proj)
    summary = payload["summary"]
    assert rc == 1, "a route that ended with 12 violations was certified clean"
    assert summary["tool_violation_total"] == 12
    assert summary["summary_violation_total"] == 0
    # The number the gate REPORTS must be the one that can still fail a design.
    assert summary["real_violation_total"] == 12
    rules = [f["rule"] for f in payload["findings"]]
    assert "DRC_SUMMARY_CONTRADICTS_TOOL" in rules
    assert summary["tool_contradictions"][0] == {
        "file": "reports/phase3/drc_router.rpt",
        "summary_says": 0, "tool_says": 12}


def test_summary_edit_still_reddens(tmp_path):
    """ART-DRC-ROUTER-SUMMARY must KEEP reddening, with the number it always
    reported. Closing the tool-output path by breaking the summary path would
    trade one hole for another."""
    proj = _drc_project(tmp_path, _router_report(17, [101, 11, 3, 0]))
    rc, payload = _drc(proj)
    assert rc == 1
    assert payload["summary"]["real_violation_total"] == 17
    assert payload["summary"]["tool_violation_total"] == 0
    assert "DRC_SUMMARY_CONTRADICTS_TOOL" in [f["rule"]
                                              for f in payload["findings"]]


def test_agreement_passes_and_states_what_it_corroborated(tmp_path):
    """The green arm. Same fixture shape, tool and summary agreeing at 0: PASS,
    and the PASS says the agreement was MEASURED against 1 source rather than
    assumed from silence."""
    proj = _drc_project(tmp_path, _router_report(0, [101, 11, 3, 0]))
    rc, payload = _drc(proj)
    assert rc == 0
    assert payload["summary"]["tool_corroborated_files"] == 1
    assert payload["summary"]["tool_uncorroborated_files"] == 0
    assert payload["summary"]["tool_contradictions"] == []


def test_report_without_router_grammar_is_uncorroborated_not_failed(tmp_path):
    """A report carrying no tool transcript has no final word to check against.
    That is DISCLOSED as an uncorroborated file — never collapsed to a zero
    (which would credit silence as cleanliness) and never turned into a refusal
    (which would redden every report of a different dialect)."""
    proj = _drc_project(tmp_path, _router_report(0, None))
    rc, payload = _drc(proj)
    assert rc == 0
    assert payload["summary"]["tool_corroborated_files"] == 0
    assert payload["summary"]["tool_uncorroborated_files"] == 1


# ══════════════════════════════════════════════════════════════════════
# Step 9 — the enumerated primitives must reach the verdict
# ══════════════════════════════════════════════════════════════════════
def test_primitive_swap_reddens_and_names_the_primitives(tmp_path):
    """ART-NETLIST-PRIMITIVE-SWAP. Every instantiation site swapped for a
    primitive whose output is inverted with respect to what synthesis produced,
    while the file the tool itself wrote sits beside it unchanged."""
    proj = _netlist_project(tmp_path, _netlist("$_AND_"), _netlist("$_NAND_"))
    rc, report = _netlist_gate(proj)
    assert rc == 1, "a netlist that no longer implements the RTL was certified"
    census = report["stats"]["cell_census"]
    assert census["status"] == "CONTRADICTS"
    # The enumeration was already in the report before this change; what is new
    # is that it decides something. Both sides must be named.
    assert census["cell_types_differing"] == {
        "$_AND_": {"audited": 12, "tool": 0},
        "$_NAND_": {"audited": 0, "tool": 12}}
    assert "CELL_CENSUS_CONTRADICTS_TOOL" in [f["category"]
                                              for f in report["findings"]]


def test_matching_census_passes_and_states_its_sources(tmp_path):
    """The green arm: same fixture, same primitive on both sides."""
    proj = _netlist_project(tmp_path, _netlist("$_NAND_"), _netlist("$_NAND_"))
    rc, report = _netlist_gate(proj)
    assert rc == 0
    assert report["summary"]["cell_census_corroborating_sources"] == 1
    assert report["summary"]["cell_census_status"] == "AGREE"


def test_absent_tool_netlist_is_disclosed_not_failed(tmp_path):
    """No tool-emitted sibling: 0 corroborating sources, said out loud, verdict
    unchanged. 13 of the 16 netlists published under `benchmark-data/` are in
    this state, so a refusal here would be a ruler change reported as a defect."""
    proj = _netlist_project(tmp_path, _netlist("$_NAND_"), None)
    rc, report = _netlist_gate(proj)
    assert rc == 0
    assert report["summary"]["cell_census_corroborating_sources"] == 0
    assert report["summary"]["cell_census_status"] == "NO_TOOL_EMITTED_NETLIST"


def test_tool_output_is_not_compared_against_itself(tmp_path):
    """A gate pointed straight AT the tool's own output has no second copy. The
    check must report that, not compare a file with itself and call the
    inevitable agreement corroboration."""
    proj = _netlist_project(tmp_path, _netlist("$_NAND_"), _netlist("$_NAND_"))
    r = _run(NETLIST_GATE, ["--netlist", "phase2/stage2/synth/netlist_yosys.v"],
             cwd=proj)
    report = json.loads(r.stdout)
    assert r.returncode == 0
    assert report["summary"]["cell_census_corroborating_sources"] == 0
