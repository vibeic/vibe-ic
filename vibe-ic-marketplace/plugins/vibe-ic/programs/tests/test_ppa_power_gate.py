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




def _refused(r):
    """A refusal is rc 2 AND no finding. Asserting only the code would pass on
    a gate that had started reporting design findings as refusals."""
    return (r.returncode == 2 and "[FAIL]" not in r.stdout
            and "[PASS]" not in r.stdout
            and "POWER_TOTAL_OVER_BUDGET" not in r.stdout
            and any(l.lstrip().startswith("INCOMPLETE")
                    for l in r.stdout.splitlines()))


# ── 1. the threshold comes from the CONTRACT ──────────────────────────────




def test_the_contract_outranks_l19_end_to_end(tmp_path):
    """L19 says 1000 uW (the design would pass); the contract says 100 uW (it
    would not). The contract wins, and the superseded value is in the JSON."""
    proj = _project(tmp_path, rpt=_rpt(), l19=1000.0,
                    contract=_contract(1.0e-04))
    out = tmp_path / "out.json"
    doc = json.loads(out.read_text())
    assert doc["requirement"]["authority"] == pw.AUTHORITY_CONTRACT
    assert [s["max_uw"] for s in doc["requirement_superseded"]] == [1000.0]






# ── 2. the ACTIVITY BASIS gate ────────────────────────────────────────────












# ── 3. VACUOUS — missing input is rc 2 with a marker, never 0 and never 1 ─


def test_an_unreadable_report_is_disclosed_and_not_counted_as_clean(tmp_path):
    """"I could not read it" and "I read it and it was empty" must never
    produce the same verdict. The unreadable file is named in the JSON."""
    proj = _project(tmp_path, rpt=_rpt(), l19=1000.0)
    bad = proj / "reports" / "phase3" / "power_bad.rpt"
    bad.write_bytes(b"\xff\xfe\x00\x00not utf-8 at all")
    out = tmp_path / "out.json"
    doc = json.loads(out.read_text())
    files = [d["file"] for d in doc["reports_read"]]
    assert any("power_bad.rpt" in f for f in files), files
    # It decoded with replacement rather than failing, so it is READ and states
    # no Total row — which is disclosed as such, not dropped.
    row = next(d for d in doc["reports_read"] if "power_bad.rpt" in d["file"])
    assert row["total_power_W"] is None
    assert row["total_not_measured_reason"]




# ── 4. the JSON a downstream consumer reads ───────────────────────────────
def test_the_json_carries_the_basis_and_its_evidence(tmp_path):
    proj = _project(tmp_path, l19=1000.0,
                    rpt=_rpt("vector_vcd", fail="READ_VCD_FAIL: boom"))
    out = tmp_path / "out.json"
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












@pytest.mark.parametrize("authority", [
    "declared-budget", "missing-budget", "other-tech-baseline",
])
def test_mixed_unstated_and_known_basis_reaches_the_declared_disposition(
        tmp_path, authority):
    """An unknown basis stays visible beside a known one through the real CLI.

    Neither a basis-free budget nor the absence of one makes the two reports
    comparable. The existing foreign-technology disposition remains distinct
    from both a comparison and an outstanding requirement.
    """
    if authority == "other-tech-baseline":
        import test_issue2147_signoff_rows_are_consumed as signoff
        proj = signoff._project(tmp_path, built_on=signoff.LIB_B)
    else:
        proj = _project(tmp_path, rpt=_rpt(),
                        l19=1000.0 if authority == "declared-budget" else None)
    retained = proj / "steps" / "33_retained_power"
    retained.mkdir(parents=True)
    (retained / "power.rpt").write_text(_rpt(None))
    out = tmp_path / "power_budget.json"
    doc = json.loads(out.read_text())
    assert {row["activity_basis"] for row in doc["reports_read"]} == {
        pw.BASIS_UNSTATED, pw.BASIS_VECTORLESS}
    assert "UNSTATED, VECTORLESS" in doc["activity_basis_conflict"]
    assert doc.get("comparison") is None
    assert not doc["findings"]
    if authority == "declared-budget":
        assert doc["verdict"] == "INCOMPLETE"
        assert doc["judgement"]["code"] == "ACTIVITY_BASIS_CONFLICT"
        assert doc["power_budget_uw"] == 1.0e-3 / 1.0e-6
    else:
        assert doc["power_budget_uw"] is None
        assert doc["requirement"] is None
        assert doc["judgement"]["code"] == "NO_REQUIREMENT"
        if authority == "missing-budget":
            assert doc["verdict"] == "INCOMPLETE"
        else:
            import _flow_reason_taxonomy as taxonomy
            assert doc["verdict"] == "NOT_APPLICABLE"
            assert doc["reason_class"] == taxonomy.DESIGN_DECLARED_NA
            assert doc["disposition"]["signoff_row_reason"] == (
                "baseline_not_attributed_to_this_technology")
