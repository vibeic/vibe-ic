#!/usr/bin/env python3
"""vibe-ic#2091 — a clock period the design never stated must be reported as an
ASSUMPTION, and a timing sign-off measured against it must say so.

Measured on opentitan_aes x sky130A: the input states no target clock period
anywhere (its only frequency is a reference point attached to an entropy-rate
figure), the run signed off against 10 ns, and post-route WNS reached
-42.140 ns with nothing in any artefact saying the 10 ns was not a spec.

BOTH DIRECTIONS ARE ASSERTED HERE, deliberately:
  * the ASSUMED case must be flagged AND must redden the disclosure gate when
    the record stays silent (a gate that cannot fail is not a gate); and
  * the DESIGN-OWNED case must be byte-for-byte unaffected — the fix must not
    relabel a design that DID state its period.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import clock_target_provenance as ctp          # noqa: E402


def _project(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    return p


def _signoff(project: Path, payload: dict) -> Path:
    d = project / "reports" / "phase3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "post_route_summary.json"
    f.write_text(json.dumps(payload, indent=2) + "\n")
    return f


def _provenance(project: Path, rep: dict) -> Path:
    d = project / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "clock_target_provenance.json"
    f.write_text(json.dumps(rep, indent=2) + "\n")
    return f


# ── the input states NOTHING: assumed, declared, and enforceable ────────────
def test_absent_target_is_reported_as_assumed(tmp_path):
    """The #2091 shape: no period anywhere in the input."""
    proj = _project(tmp_path, "no_target")
    # The only frequency in the document is a reference point on an unrelated
    # rate figure — exactly the sentence the measured input carries.
    (proj / "input" / "docs" / "L1_overview.md").write_text(
        "# Overview\n\n- rates ranging from 343 Mbit/s to 0.042 Mbit/s "
        "(at 100 MHz).\n")
    rep = ctp.resolve(proj, pdk="sky130A", applied_period_ns=10.0)
    assert rep["assumed"] is True
    assert rep["tier"] == ctp.PLUGIN_DEFAULT_TIER
    assert rep["period_ns"] == 10.0
    # The assumption must be ACTIONABLE, not merely labelled.
    assert "no target clock period is stated" in rep["would_have_stated"]
    assert ctp.ASSUMED_DISCLOSURE in rep["disclosure"]


def test_absent_target_and_no_applied_period_is_not_determined(tmp_path):
    """"Could not read it" is not "read it and it was 20 ns"."""
    proj = _project(tmp_path, "silent")
    rep = ctp.resolve(proj, pdk="sky130A")
    assert rep["tier"] == ctp.NOT_DETERMINED_TIER
    assert rep["period_ns"] is None
    assert rep["assumed"] is False










# ── the input DOES state a period: nothing may change ───────────────────────
def test_staged_sdc_is_design_owned_and_gate_is_silent(tmp_path):
    """The spm-shaped control: a design that states its period is untouched."""
    proj = _project(tmp_path, "stated")
    c = proj / "input" / "constraints"
    c.mkdir(parents=True)
    (c / "constraint.sdc").write_text(
        "create_clock -name core_clock -period 24.0 [get_ports clk]\n")
    rep = ctp.resolve(proj, pdk="gf180mcuD", applied_period_ns=24.0)
    assert rep["assumed"] is False
    assert rep["tier"] == "staged_sdc"
    assert rep["period_ns"] == 24.0
    assert "constraint.sdc" in str(rep["cite"])
    _provenance(proj, rep)
    _signoff(proj, {"verdict": "MET"})
    # No disclosure is demanded of a design that declared its own period.


def test_l8_declared_period_outranks_the_default(tmp_path):
    proj = _project(tmp_path, "l8")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"clock_domains": [{"name": "clk", "period_ns": 12.5}]}))
    rep = ctp.resolve(proj, pdk="sky130A", applied_period_ns=20.0)
    assert rep["tier"] == "l8_declared"
    assert rep["assumed"] is False
    assert rep["period_ns"] == 12.5


def test_contradictory_l8_is_not_a_declaration(tmp_path):
    """Two different periods is a refusal, never a vote by list order."""
    proj = _project(tmp_path, "l8_split")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"clock_domains": [{"name": "a", "period_ns": 10.0},
                           {"name": "b", "period_ns": 24.0}]}))
    rep = ctp.resolve(proj, pdk="sky130A", applied_period_ns=20.0)
    assert rep["assumed"] is True
    assert rep["tier"] == ctp.PLUGIN_DEFAULT_TIER


def test_a_retracted_doc_period_is_not_a_declaration(tmp_path):
    """vibe-ic#712 — the prose polarity consult, on the value that reaches the
    SDC. A withdrawn statement must not be published as a spec."""
    proj = _project(tmp_path, "retracted")
    (proj / "input" / "docs" / "L9_constraints.md").write_text(
        "# Constraints\n\nThe clock period is no longer 10 ns for this "
        "build.\n")
    rep = ctp.resolve(proj, pdk="sky130A", applied_period_ns=20.0)
    assert rep["assumed"] is True, rep
    assert rep["period_ns"] == 20.0


def test_a_live_doc_period_is_read(tmp_path):
    """The polarity consult must not swallow a LIVE statement (a check that
    refuses everything is not a check)."""
    proj = _project(tmp_path, "live")
    (proj / "input" / "docs" / "L9_constraints.md").write_text(
        "# Constraints\n\nThe clock period is 8 ns for this build.\n")
    rep = ctp.resolve(proj, pdk="sky130A", applied_period_ns=20.0)
    assert rep["assumed"] is False, rep
    assert rep["tier"] == "doc_prose"
    assert rep["period_ns"] == 8.0


def test_cli_exit_codes_separate_the_three_outcomes(tmp_path):
    proj = _project(tmp_path, "cli")
    prog = str(PROGRAMS / "clock_target_provenance.py")
    r = subprocess.run([sys.executable, prog, str(proj), "--pdk", "sky130A"],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.stdout
    r = subprocess.run([sys.executable, prog, str(proj), "--pdk", "sky130A",
                        "--applied-period-ns", "10"],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    c = proj / "input" / "constraints"
    c.mkdir(parents=True)
    (c / "x.sdc").write_text("create_clock -period 24 [get_ports clk]\n")
    r = subprocess.run([sys.executable, prog, str(proj), "--pdk", "sky130A",
                        "--applied-period-ns", "24"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ── the DIALOGUE track: the question must actually be asked ────────────────


def _layers(tmp_path: Path, clock_rec: dict) -> Path:
    d = tmp_path / "layers"
    d.mkdir()
    (d / "L1_DATASHEET.json").write_text(json.dumps(
        {"chip_name": "part_x",
         "ports": [{"name": "clk_i", "direction": "input", "width": 1},
                   {"name": "data_o", "direction": "output", "width": 8}]}))
    (d / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"clock_domains": [clock_rec]}))
    return d








# ── the RUNNER wiring: the record actually gets the stamp ──────────────────
#
# The two helpers live in `clock_target_provenance`, not in the runner: the
# runner orchestrates and `test_ppa_runner_extraction_ledger` refuses a
# `clock`-named function defined in it. This asserts the runner still CALLS
# them, so moving the logic out cannot quietly unwire it.




def test_runner_stamps_the_assumption_into_the_signoff_record(tmp_path):
    proj = _project(tmp_path, "runner_assumed")
    _signoff(proj, {"verdict": "VIOLATED", "setup_wns_ns": -42.140})
    ctp.emit_report(proj, pdk="sky130A", applied_period_ns=10.0)
    prov = json.loads((proj / ctp.PROVENANCE_REL).read_text())
    assert prov["assumed"] is True, prov
    assert ctp.stamp_signoff_records(proj), "nothing was stamped"
    rec = json.loads(
        (proj / "reports/phase3/sta/post_route_summary.json").read_text())
    assert rec["clock_period_assumed"] is True
    assert ctp.ASSUMED_DISCLOSURE in rec["clock_period_note"]
    # The verdict it was carrying is untouched.
    assert rec["verdict"] == "VIOLATED"
    assert rec["setup_wns_ns"] == -42.140
    # And the gate that enforces this is now green on the stamped record.


def test_runner_stamps_nothing_when_the_design_owns_the_period(tmp_path):
    """The spm-shaped control — bytes unchanged."""
    proj = _project(tmp_path, "runner_stated")
    c = proj / "input" / "constraints"
    c.mkdir(parents=True)
    (c / "constraint.sdc").write_text(
        "create_clock -name core_clock -period 24.0 [get_ports clk]\n")
    rec_path = _signoff(proj, {"verdict": "MET"})
    before = rec_path.read_bytes()
    ctp.emit_report(proj, pdk="gf180mcuD", applied_period_ns=24.0)
    prov = json.loads((proj / ctp.PROVENANCE_REL).read_text())
    assert prov["assumed"] is False and prov["tier"] == "staged_sdc", prov
    assert ctp.stamp_signoff_records(proj) == [], "a design-owned period was stamped"
    assert rec_path.read_bytes() == before


# ── L19 records the ABSENCE explicitly (the icaes expectation
#    `l19-clock-frequency-and-period-not-stated`) ────────────────────────────
import l19_constraint_token_emit as l19e  # noqa: E402


def _l19_project(tmp_path: Path, name: str, pdk: str) -> Path:
    proj = _project(tmp_path, name)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"doc_id": "L19", "fields": {"pdk_target": pdk}}))
    return proj


def _l19_fields(proj: Path) -> dict:
    return json.loads(
        (proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text()
    )["fields"]


def test_l19_records_an_unstated_clock_target_as_an_absence(tmp_path):
    proj = _l19_project(tmp_path, "l19_absent", "sky130A")
    (proj / "input" / "docs" / "aes_README.md").write_text(
        "- rates from 343 Mbit/s to 0.042 Mbit/s (at 100 MHz).\n")
    rep = l19e.run(proj)
    assert rep["status"] == "OK", rep
    ct = _l19_fields(proj)["clock_target"]
    assert ct["status"] == "NOT_STATED", ct
    # NOTHING is defaulted — the absence is the record, not a number.
    assert ct["period_ns"] is None
    assert "no target clock period is stated" in ct["reason"]
    assert "ASSUMPTION" in ct["note"]


def test_l19_records_a_stated_clock_target_as_declared(tmp_path):
    """The control: a design that states its period is recorded as DECLARED."""
    proj = _l19_project(tmp_path, "l19_stated", "gf180mcuD")
    c = proj / "input" / "constraints"
    c.mkdir(parents=True)
    (c / "constraint.sdc").write_text(
        "create_clock -name core_clock -period 24.0 [get_ports clk]\n")
    l19e.run(proj)
    ct = _l19_fields(proj)["clock_target"]
    assert ct["status"] == "DECLARED"
    assert ct["period_ns"] == 24.0
    assert ct["tier"] == "staged_sdc"
    assert "constraint.sdc" in str(ct["evidence"])


def test_l19_never_overwrites_a_clock_target_another_producer_owns(tmp_path):
    proj = _l19_project(tmp_path, "l19_owned", "sky130A")
    p = proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    doc = json.loads(p.read_text())
    doc["fields"]["clock_target"] = {"status": "DECLARED", "period_ns": 5.0,
                                     "owner": "someone_else"}
    p.write_text(json.dumps(doc))
    rep = l19e.run(proj)
    assert rep["clock_target"] is None, rep
    assert _l19_fields(proj)["clock_target"]["owner"] == "someone_else"


def test_l19_dry_run_writes_nothing(tmp_path):
    proj = _l19_project(tmp_path, "l19_dry", "sky130A")
    before = (proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_bytes()
    l19e.run(proj, dry_run=True)
    assert (proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
            ).read_bytes() == before
