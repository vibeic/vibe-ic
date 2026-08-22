#!/usr/bin/env python3
"""Three chip-AGNOSTIC HONESTY defects surfaced by an spm benchmark re-run.

All three are the same dangerous class: a gate REPORTING THE WRONG THING.

  D1 false-FAIL  — `harness_exact_selfverify` gate C blocked a PASSING TB whose
                   summary read `checks=10016 errors=0`: the unanchored
                   `[1-9]\\d*\\s+ERRORS?` alternative bound a DIFFERENT field's
                   digits to the `errors` token.
  D2 fabrication — `spec_test_debug_extract` minted scan/JTAG/BIST requirements
                   from JSON SCHEMA KEYS whose VALUES were empty (`[]`/`null`/
                   `false`), i.e. for designs with NO DFT at all.
  D3 false-clean — an ENV_UNAVAILABLE waiver written when a step COULD NOT RUN
                   survived into a later run where the step actually EXECUTED
                   and FAILED, excusing a real failure.

Every fix carries BOTH directions (§4.05): the guard still catches what it must
(positive) and no longer fires on what it must not (negative).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import harness_exact_selfverify as hes      # noqa: E402
import spec_test_debug_extract as stde      # noqa: E402
import waiver_staleness as ws               # noqa: E402
import waivers_materialize as wm            # noqa: E402


# ===========================================================================
# DEFECT 1 — gate C must not false-BLOCK a passing TB
# ===========================================================================
# --- NEGATIVE side: these PASSING forms must NOT be read as failures --------
@pytest.mark.parametrize("blob", [
    "checks=10016 errors=0",                       # the exact spm repro
    "checks=10016 errors=0\nTest complete.",
    "0 errors",
    "errors: 0",
    "errors = 0",
    "ERRORS=0",                                    # uppercase: also not a fail
    "ERRORS: 0",
    "no errors",
    "NO ERRORS DETECTED",
    "vectors=4096 errors=0",
    "cycles 250000 errors 0",
    "total_checks=999 errors=0 warnings=0",
])
def test_d1_passing_error_summaries_are_not_blocked(blob):
    ok, why = hes._tb_verdict(blob)
    assert ok is not False, f"false-BLOCK on a PASSING summary {blob!r}: {why}"


def test_d1_exact_spm_repro_is_a_pass_not_a_block():
    """The reproduced spm case: a zero-error summary is a PASS verdict."""
    ok, why = hes._tb_verdict("checks=10016 errors=0")
    assert ok is True, why
    assert "zero error count" in why


def test_d1_unanchored_digits_no_longer_bind_to_errors():
    """The regex itself must no longer match a foreign field's digits."""
    assert not hes._TB_FAIL_RE.search("checks=10016 errors=0")
    assert not hes._TB_FAIL_RE.search("cycles 250000 errors 0")


# --- POSITIVE side: genuine failures must STILL be caught -------------------
@pytest.mark.parametrize("blob", [
    "errors=7",
    "errors = 7",
    "errors: 3",
    "3 ERRORS",
    "3 errors",
    "12 errors detected",
    "checks=10016 errors=7",                       # real failure, same shape
    "checks=10016 errors=0\nerrors=7",             # zero THEN a real failure
    "TEST FAILED",
    "FAILED",
    "FAIL",
    "TEST_FAIL",
    "$error(\"bad\");",
    "$fatal(1);",
    "FATAL: assertion violated",
    "Assertion failed at time 250 - FAILED",
    # COUNT-BINDING: the trailing `0` is claimed by the `warnings` LABEL, so
    # the error count is the LEFT-bound 3 — a real failure, not a zero count.
    "3 errors 0 warnings",
    "errors 7",
    "errors 7 warnings 0",
])
def test_d1_genuine_failures_are_still_caught(blob):
    ok, why = hes._tb_verdict(blob)
    assert ok is False, f"MISSED a genuine failure {blob!r}: {why}"


def test_d1_zero_count_never_rescues_a_real_failure():
    """A blob containing BOTH a zero count and a real failure must FAIL —
    the fail token wins outright, the zero-count PASS never rescues it."""
    ok, _ = hes._tb_verdict("checks=10016 errors=0\nlater: errors=7\n")
    assert ok is False
    ok2, _ = hes._tb_verdict("errors=0\nTEST FAILED\n")
    assert ok2 is False


def test_d1_bare_error_banner_still_blocks_without_a_pass_or_zero_count():
    """The uppercase-ERROR fallback is intact for a blob with no PASS banner
    and no explicit zero count."""
    ok, _ = hes._tb_verdict("ERROR at time 40")
    assert ok is False


def test_d1_mismatch_summary_unaffected():
    assert hes._tb_verdict("Mismatches: 0 in 100")[0] is True
    assert hes._tb_verdict("Mismatches: 5 in 100")[0] is False


def test_d1_inconclusive_still_inconclusive():
    assert hes._tb_verdict("simulation finished")[0] is None


# ===========================================================================
# DEFECT 2 — no fabricated scan/JTAG/BIST from an EMPTY schema key
# ===========================================================================
_SKELETON_LDOC = json.dumps({
    "dft_present": False,
    "scan_chain": [],
    "scan_chains": [],
    "jtag_tap": None,
    "bist": {},
    "test_mode": "",
    "debug_port": None,
}, indent=2)


def test_d2_skeleton_ldoc_emits_zero_requirements():
    """NEGATIVE: a schema key with an empty/false/null VALUE states nothing."""
    items = stde.extract(_SKELETON_LDOC)
    assert items == [], f"FABRICATED requirements from empty schema keys: {items}"


def test_d2_nested_all_empty_subtree_emits_nothing():
    """A parent key must not survive when its whole subtree is empty."""
    doc = json.dumps({"dft": {"scan_chain": [], "jtag_tap": None,
                              "bist": {}, "test_mode": ""}}, indent=2)
    assert stde.extract(doc) == []


def test_d2_zero_counts_emit_nothing():
    doc = json.dumps({"scan_chains": 0, "bist_blocks": 0, "jtag_taps": 0})
    assert stde.extract(doc) == []


def test_d2_declared_dft_still_emits_requirements():
    """POSITIVE: a design that GENUINELY declares DFT keeps its requirements."""
    doc = json.dumps({
        "scan_chain": ["scan_en", "scan_in", "scan_out"],
        "jtag_tap": {"signals": ["TMS", "TCK", "TDI", "TDO"]},
        "bist": {"kind": "MBIST"},
        "test_mode": "test_mode",
    }, indent=2)
    kinds = {i["kind"] for i in stde.extract(doc)}
    assert kinds == {"scan_chain", "jtag_tap", "bist", "test_mode"}, kinds


def test_d2_mixed_doc_emits_only_the_non_empty_facet():
    """The declared facet fires; the empty ones stay silent."""
    doc = json.dumps({"scan_chain": [], "jtag_tap": None,
                      "bist": {"kind": "LBIST"}, "test_mode": ""}, indent=2)
    kinds = {i["kind"] for i in stde.extract(doc)}
    assert kinds == {"bist"}, kinds


def test_d2_prose_statement_still_fires():
    """POSITIVE: plain prose is untouched by the JSON blanking pass."""
    kinds = {i["kind"] for i in stde.extract(
        "The design provides a scan chain and a JTAG TAP controller for debug.")}
    assert {"scan_chain", "jtag_tap"} <= kinds


def test_d2_no_anchor_still_returns_empty():
    assert stde.extract("An 8-bit adder with a synchronous reset.") == []


# ===========================================================================
# DEFECT 3 — a waiver must NEVER excuse a failure that actually happened
# ===========================================================================
def _project(tmp_path: Path, drc_status: str) -> Path:
    """A project whose phase3 report records the DRC step with `drc_status`."""
    proj = tmp_path / "proj"
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3_one_shot.json").write_text(json.dumps({
        "run_id": "run-B",
        "steps": [{"name": "drc", "status": drc_status},
                  {"name": "lvs", "status": "ENV_UNAVAILABLE"}],
    }, indent=2))
    return proj


_ENV_WAIVER = {
    "id": 33,
    "step": "drc",
    "verdict_tier": "ENV_UNAVAILABLE",
    "_env_unavailable": True,
    "review_required": True,
    "ticket": "TCK-1",
    "reason": "DRC tool absent on this host",
    "_waiver_condition": {"kind": ws.CONDITION_STEP_DID_NOT_EXECUTE,
                          "step": "drc", "run_id": "run-A"},
}


# --- POSITIVE side: a GENUINE ENV_UNAVAILABLE is still honored --------------
def test_d3_genuine_env_unavailable_is_honored(tmp_path):
    proj = _project(tmp_path, "ENV_UNAVAILABLE")
    ok, why = ws.condition_holds(_ENV_WAIVER, proj)
    assert ok is True, why


def test_d3_honored_when_there_is_no_evidence_at_all(tmp_path):
    """No report yet -> absence of evidence must not manufacture a rejection."""
    proj = tmp_path / "empty"
    proj.mkdir()
    ok, why = ws.condition_holds(_ENV_WAIVER, proj)
    assert ok is True, why


@pytest.mark.parametrize("status", ["SKIP", "SKIPPED", "NOT_RUN", "PENDING"])
def test_d3_other_did_not_run_statuses_are_honored(tmp_path, status):
    ok, _ = ws.condition_holds(_ENV_WAIVER, _project(tmp_path, status))
    assert ok is True


def test_d3_human_judgment_waiver_is_never_touched(tmp_path):
    """A non-ENV_UNAVAILABLE waiver carries no run-condition and is unaffected
    even when its step ran and failed."""
    human = {"id": 33, "step": "drc", "reason": "known benign geometry",
             "approver": "foundry-ae"}
    ok, _ = ws.condition_holds(human, _project(tmp_path, "FAIL"))
    assert ok is True


# --- NEGATIVE side: a STALE waiver must be REFUSED --------------------------
def test_d3_stale_waiver_after_step_ran_and_failed_is_refused(tmp_path):
    """THE FALSE-CLEAN CASE: the step EXECUTED and FAILED -> the waiver written
    when it could not run must NOT excuse that failure."""
    proj = _project(tmp_path, "FAIL")
    ok, why = ws.condition_holds(_ENV_WAIVER, proj)
    assert ok is False, "stale waiver EXCUSED a real failure (false-clean)"
    assert "STALE WAIVER REFUSED" in why
    assert "not excused" in why.lower()


@pytest.mark.parametrize("status", ["FAIL", "PASS", "OK", "ERROR", "BLOCK"])
def test_d3_any_execution_status_breaks_the_condition(tmp_path, status):
    """Any status that is not a did-not-run status is POSITIVE evidence the
    step ran, which breaks the ENV_UNAVAILABLE condition."""
    ok, _ = ws.condition_holds(_ENV_WAIVER, _project(tmp_path, status))
    assert ok is False


def test_d3_unstamped_legacy_waiver_is_also_refused(tmp_path):
    """The guard must not be defeatable by simply omitting the stamp — a legacy
    ENV_UNAVAILABLE entry carries the same IMPLICIT condition."""
    legacy = {k: v for k, v in _ENV_WAIVER.items() if k != "_waiver_condition"}
    ok, why = ws.condition_holds(legacy, _project(tmp_path, "FAIL"))
    assert ok is False, why


def test_d3_step_executed_evidence_reader(tmp_path):
    assert ws.step_executed(_project(tmp_path, "FAIL"), "drc") is True
    assert ws.step_executed(_project(tmp_path, "ENV_UNAVAILABLE"), "drc") is False
    assert ws.step_executed(_project(tmp_path, "FAIL"), "lvs") is False
    assert ws.step_executed(_project(tmp_path, "FAIL"), "sta") is None


def test_d3_prune_mapping_drops_only_the_stale_entry(tmp_path):
    proj = _project(tmp_path, "FAIL")
    mapping = {33: dict(_ENV_WAIVER),
               34: {**_ENV_WAIVER, "id": 34, "step": "lvs"}}
    refused = ws.prune_stale_mapping(mapping, proj)
    assert 33 in refused and 34 not in refused
    assert 33 not in mapping and 34 in mapping   # lvs deferral survives


def test_d3_stamp_records_the_condition_and_run_identity(tmp_path):
    proj = _project(tmp_path, "ENV_UNAVAILABLE")
    stamped = ws.stamp({"id": 33, "step": "drc", "_env_unavailable": True}, proj)
    cond = stamped["_waiver_condition"]
    assert cond["kind"] == ws.CONDITION_STEP_DID_NOT_EXECUTE
    assert cond["step"] == "drc"
    assert cond["run_id"]                      # run identity captured


def test_d3_stamp_leaves_a_human_judgment_waiver_alone(tmp_path):
    proj = _project(tmp_path, "ENV_UNAVAILABLE")
    human = {"id": 33, "step": "drc", "reason": "benign", "approver": "foundry-ae"}
    assert "_waiver_condition" not in ws.stamp(human, proj)


# --- the FILE-level survival path (the actual spm repro shape) --------------
def _write_autogen_waivers(proj: Path, entries) -> Path:
    p = proj / "waivers.json"
    p.write_text(json.dumps({
        "_schema_version": "1",
        "_generator": "waivers_materialize.py",
        "waived_steps": entries,
    }, indent=2))
    return p


def test_d3_stale_waiver_file_is_pruned_when_the_step_ran(tmp_path):
    """NEGATIVE: the carried-over FILE must not survive a run that executed
    (and failed) the step it excuses."""
    proj = _project(tmp_path, "FAIL")
    wpath = _write_autogen_waivers(proj, [dict(_ENV_WAIVER)])
    refused = wm.prune_stale(proj)
    assert len(refused) == 1
    assert "_refused_reason" in refused[0]
    data = json.loads(wpath.read_text())
    assert data["waived_steps"] == []
    assert data["_refused_stale_waivers"]        # rejection is AUDITABLE


def test_d3_genuine_waiver_file_survives(tmp_path):
    """POSITIVE: the step still could not run -> the file is left intact."""
    proj = _project(tmp_path, "ENV_UNAVAILABLE")
    wpath = _write_autogen_waivers(proj, [dict(_ENV_WAIVER)])
    assert wm.prune_stale(proj) == []
    assert len(json.loads(wpath.read_text())["waived_steps"]) == 1


def test_d3_human_authored_waiver_file_is_never_pruned(tmp_path):
    """A human-authored waivers.json wins untouched — the same invariant the
    materializer already guarantees."""
    proj = _project(tmp_path, "FAIL")
    p = proj / "waivers.json"
    p.write_text(json.dumps({"waived_steps": [dict(_ENV_WAIVER)]}, indent=2))
    before = p.read_text()
    assert wm.prune_stale(proj) == []
    assert p.read_text() == before


def test_d3_missing_waiver_file_is_a_noop(tmp_path):
    assert wm.prune_stale(_project(tmp_path, "FAIL")) == []
