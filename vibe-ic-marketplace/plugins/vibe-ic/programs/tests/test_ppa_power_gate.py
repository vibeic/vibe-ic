#!/usr/bin/env python3
"""Tests for `power_total_vs_budget_check` AS THE FLOW INVOKES IT — the two
things spec §7.2 added to it, measured through the CLI and the exit code rather
than through the functions underneath.

    1. the threshold comes from the CONTRACT, not from the gate's own idea of
       one, with L19 as the fallback and `--budget-uw` above both;
    2. a watt figure whose ACTIVITY BASIS is unknown, self-contradicted, or
       different from the one the requirement was written against is not
       compared at all — rc 2, never rc 0, and never rc 1.

`programs/tests/test_power_total_vs_budget_check.py` continues to hold the
gate's ORIGINAL contract (the L19 comparison, the ledger mutation, the empty
tree, the flow-consumer tier) and is deliberately not duplicated here. This file
is only the delta, so a failure in it names the new rule and not the old one.

rc 1 IS A CLAIM ABOUT SILICON. Every assertion below that expects a refusal
asserts `== 2` and separately asserts the run did NOT report a finding, because
"the design is over budget" and "I do not know what activity model produced this
number" must never be the same exit code.

Fixtures are SYNTHETIC and carry no process, foundry or chip token.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
PROG = _HERE.parent / "power_total_vs_budget_check.py"
sys.path.insert(0, str(_HERE.parent))
from _ppa import power as pw          # noqa: E402

_BANNER = "OpenSTA 2.7.0 f21d4a3878 Copyright (c) 2026, Parallax Software\n"
#: Total power 3.12e-04 W = 312 uW, the same figure the sibling file uses so the
#: two can be read side by side.
_TABLE = """\
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             2.75e-04   8.19e-06   5.28e-10   2.83e-04  90.5%
Combinational          1.83e-05   1.13e-05   3.17e-10   2.95e-05   9.5%
----------------------------------------------------------------
Total                  2.93e-04   1.95e-05   8.45e-10   3.12e-04 100.0%
"""


def _rpt(mode="vectorless_sdc", *, annotated=None, fail=None):
    parts = [_BANNER]
    if fail:
        parts.append(fail + "\n")
    if annotated is not None:
        parts.append(f"Annotated {annotated} pin activities.\n")
    if mode is not None:
        parts.append(f"POWER_ANALYSIS_MODE: {mode}\n")
    parts.append(_TABLE)
    return "".join(parts)


def _project(tmp_path, *, rpt=None, l19=None, contract=None):
    proj = tmp_path / "run"
    d = proj / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    if rpt is not None:
        (d / "power.rpt").write_text(rpt)
    l19dir = proj / "phase1" / "generated_docs"
    l19dir.mkdir(parents=True, exist_ok=True)
    (l19dir / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"doc_id": "L19", "fields": {"pdk_target": "generic",
                                     "power_budget_uw": l19}}))
    if contract is not None:
        (proj / "ppa_contract.json").write_text(json.dumps(contract))
    return proj


def _contract(max_w, *, basis=None, authority="SPEC-POWER-1"):
    req = {"metric": "power.total_w", "unit": "W", "limit": {"max": max_w},
           "authority": authority}
    if basis is not None:
        req["scope"] = {"activity_basis": basis}
    return {"schema": pw.CONTRACT_SCHEMA, "requirements": [req]}


def _run(proj, *args):
    return subprocess.run(
        [sys.executable, str(PROG), str(proj), *[str(a) for a in args]],
        capture_output=True, text=True)


def _refused(r):
    """A refusal is rc 2 AND no finding. Asserting only the code would pass on
    a gate that had started reporting design findings as refusals."""
    return (r.returncode == 2 and "[FAIL]" not in r.stdout
            and "[PASS]" not in r.stdout
            and "POWER_TOTAL_OVER_BUDGET" not in r.stdout
            and any(l.lstrip().startswith("INCOMPLETE")
                    for l in r.stdout.splitlines()))


# ── 1. the threshold comes from the CONTRACT ──────────────────────────────
def test_a_contract_requirement_is_an_authority_the_gate_reads(tmp_path):
    """POSITIVE. 312 uW under a 1000 uW contract limit, and the verdict names
    the contract rather than L19."""
    proj = _project(tmp_path, rpt=_rpt(), l19=None,
                    contract=_contract(1.0e-03))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("[PASS]")
    assert pw.AUTHORITY_CONTRACT in r.stdout
    assert "ppa contract requirement(s)" in r.stdout


def test_a_contract_requirement_reddens_when_the_total_exceeds_it(tmp_path):
    """NEGATIVE. Same tree, a limit the design misses. rc 1, because THIS one
    really is a claim about the design."""
    proj = _project(tmp_path, rpt=_rpt(), l19=None,
                    contract=_contract(1.0e-04))
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "POWER_TOTAL_OVER_BUDGET" in r.stdout
    assert "3.1200e+02" in r.stdout          # the total, in uW
    assert "1.0000e+02" in r.stdout          # the limit, in uW
    assert "VECTORLESS" in r.stdout          # and the basis it was judged on


def test_the_contract_outranks_l19_end_to_end(tmp_path):
    """L19 says 1000 uW (the design would pass); the contract says 100 uW (it
    would not). The contract wins, and the superseded value is in the JSON."""
    proj = _project(tmp_path, rpt=_rpt(), l19=1000.0,
                    contract=_contract(1.0e-04))
    out = tmp_path / "out.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    doc = json.loads(out.read_text())
    assert doc["requirement"]["authority"] == pw.AUTHORITY_CONTRACT
    assert [s["max_uw"] for s in doc["requirement_superseded"]] == [1000.0]


def test_the_cli_budget_outranks_the_contract(tmp_path):
    proj = _project(tmp_path, rpt=_rpt(), l19=None,
                    contract=_contract(1.0e-04))
    assert _run(proj).returncode == 1                    # contract: over
    assert _run(proj, "--budget-uw", "1000").returncode == 0   # caller: under


def test_two_contract_copies_that_disagree_are_not_an_authority(tmp_path):
    """The same rule L19 already had, at the level above it: an authority two
    documents state differently is not an authority, and taking the first would
    make the verdict depend on glob order."""
    proj = _project(tmp_path, rpt=_rpt(), l19=None,
                    contract=_contract(1.0e-03))
    (proj / "phase1" / "ppa_contract_b.json").write_text(
        json.dumps(_contract(2.0e-03)))
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "state different total-power limits" in r.stdout


# ── 2. the ACTIVITY BASIS gate ────────────────────────────────────────────
def test_a_budget_plus_a_contradicted_vcd_label_is_undetermined(tmp_path):
    """THE BRANCH THAT MATTERS MOST ON REAL DATA, and the one that separates
    this gate from the one it replaces.

    Everything a comparison needs is present: a declared limit and a total-power
    figure that fits comfortably under it. The gate still refuses, because the
    report claims its switching activity came from a VCD and carries, four lines
    up, the failure of the read that would have produced it. 8 of the 17
    published power reports are exactly this shape.

    rc 2, not rc 0: a PASS here would certify a comparison against an activity
    model that never loaded. rc 2, not rc 1: rc 1 is a claim about the design,
    and this is a claim about the measurement.
    """
    proj = _project(tmp_path, l19=1000.0, rpt=_rpt(
        "vector_vcd",
        fail="READ_VCD_FAIL: Wrong number of arguments :sta::read_vcd_file"))
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "READ_VCD_FAIL" in r.stdout
    assert "CONTRADICTED" in r.stdout


def test_zero_annotated_activities_under_a_budget_is_undetermined(tmp_path):
    """The other three published reports. OpenSTA states its own count."""
    proj = _project(tmp_path, l19=1000.0,
                    rpt=_rpt("vector_vcd", annotated=0))
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "0 pin activities" in r.stdout


def test_an_unlabelled_report_under_a_budget_is_undetermined(tmp_path):
    """6 of the 17 published reports state no basis at all. UNSTATED is not
    VECTORLESS: the gate does not get to pick the activity model the tool
    probably used."""
    proj = _project(tmp_path, l19=1000.0, rpt=_rpt(None))
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "UNSTATED" in r.stdout


def test_a_requirement_for_another_basis_does_not_judge_this_number(tmp_path):
    """The requirement side. The number fits under the limit by 3x and it is
    still not a PASS, because the limit was written against observed activity
    and the number is a vectorless estimate."""
    proj = _project(tmp_path, rpt=_rpt("vectorless_sdc"), l19=None,
                    contract=_contract(1.0e-03, basis=pw.BASIS_VCD))
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "different metrics" in r.stdout


def test_a_matching_basis_requirement_does_judge_it(tmp_path):
    """The paired positive, without which the test above would pass on a gate
    that refused every scoped requirement."""
    proj = _project(tmp_path, rpt=_rpt("vectorless_sdc"), l19=None,
                    contract=_contract(1.0e-03, basis=pw.BASIS_VECTORLESS))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("[PASS]")


def test_the_basis_census_is_printed_whatever_the_verdict(tmp_path):
    """A reader must be able to see what activity model the verdict rests on
    without opening the JSON, on the passing path too."""
    proj = _project(tmp_path, rpt=_rpt(), l19=1000.0)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Activity basis of the reports read: VECTORLESS=1" in r.stdout
    # L19 declares no basis, and the gate says so rather than implying the
    # threshold knew what it was bounding.
    assert "declares no activity basis" in r.stdout


# ── 3. VACUOUS — missing input is rc 2 with a marker, never 0 and never 1 ─
@pytest.mark.parametrize("what", ["no-report", "no-tree", "empty-report"])
def test_missing_input_refuses_with_a_marker(tmp_path, what):
    if what == "no-report":
        proj = _project(tmp_path, rpt=None, l19=1000.0)
    elif what == "empty-report":
        proj = _project(tmp_path, rpt="", l19=1000.0)
    else:
        proj = tmp_path / "bare"
        proj.mkdir()
    r = _run(proj)
    assert _refused(r), r.stdout + r.stderr
    assert "read 0 total-power figure(s)" in r.stdout
    assert "a readable Total row" in r.stdout


def test_an_unreadable_report_is_disclosed_and_not_counted_as_clean(tmp_path):
    """"I could not read it" and "I read it and it was empty" must never
    produce the same verdict. The unreadable file is named in the JSON."""
    proj = _project(tmp_path, rpt=_rpt(), l19=1000.0)
    bad = proj / "reports" / "phase3" / "power_bad.rpt"
    bad.write_bytes(b"\xff\xfe\x00\x00not utf-8 at all")
    out = tmp_path / "out.json"
    r = _run(proj, "--json", str(out))
    doc = json.loads(out.read_text())
    files = [d["file"] for d in doc["reports_read"]]
    assert any("power_bad.rpt" in f for f in files), files
    # It decoded with replacement rather than failing, so it is READ and states
    # no Total row — which is disclosed as such, not dropped.
    row = next(d for d in doc["reports_read"] if "power_bad.rpt" in d["file"])
    assert row["total_power_W"] is None
    assert row["total_not_measured_reason"]
    assert r.returncode == 0     # the good report still carries the comparison


def test_a_bad_invocation_is_not_a_design_finding(tmp_path):
    """rc 1 is a claim about silicon. Neither of these is one."""
    assert subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True).returncode == 2
    proj = _project(tmp_path, rpt=_rpt(), l19=None)
    assert _run(proj, "--budget-uw", "-5").returncode == 2


# ── 4. the JSON a downstream consumer reads ───────────────────────────────
def test_the_json_carries_the_basis_and_its_evidence(tmp_path):
    proj = _project(tmp_path, l19=1000.0,
                    rpt=_rpt("vector_vcd", fail="READ_VCD_FAIL: boom"))
    out = tmp_path / "out.json"
    assert _run(proj, "--json", str(out)).returncode == 2
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "INCOMPLETE"
    assert doc["judgement"]["code"] == "TOTAL_NOT_MEASURED"
    row = doc["reports_read"][0]
    assert row["activity_basis"] == pw.BASIS_CONTRADICTED
    assert row["declared_mode"] == "vector_vcd"
    kinds = {e["kind"] for e in row["activity_evidence"]}
    assert {"declared_mode", "activity_read_failure"} <= kinds
    # The record the gate selected is INVALID and carries no value-as-verdict.
    assert doc["selected_total"]["record"]["status"] == pw.STATUS_INVALID


def test_the_incomplete_sentinel_still_survives_the_flow_tail_cut(tmp_path):
    """The new refusal branches print more prose than the old one did, and the
    consumer keeps only the LAST characters of stdout. Asserted against the
    consumer's own functions so the two cannot drift apart."""
    import flow_compliance_check as fcc
    for proj in (_project(tmp_path / "a", l19=1000.0,
                          rpt=_rpt("vector_vcd", fail="READ_VCD_FAIL: boom")),
                 _project(tmp_path / "b", l19=None, rpt=_rpt()),
                 _project(tmp_path / "c", l19=1000.0, rpt=_rpt(None))):
        r = _run(proj)
        assert r.returncode == 2, r.stdout
        snippet = fcc.output_snippet(r.stdout, r.stderr)
        assert fcc._stdout_signals_token(
            snippet, fcc._INCOMPLETE_STDOUT_TOKEN), r.stdout
