"""ORGANIC #673 (P0) — Step-3 CDC hard-FAILs multi-clock designs on a #436
SKIPPED-CONDITION report (no cap:cdc flag) → blocks ALL of Phase 3.

The phase2 runner cannot synthesise a crossing verdict for a multi-clock
design, so it HONESTLY writes the canonical CDC JSONs
(reports/phase2/cdc/{crossing,async_input,reset_dep}.json) with
verdict=SKIPPED-CONDITION and a named reason ("multi-clock design
(root_clocks=[...]) — a real CDC tool run is required (#436)"). The
pre-#673 cdc_crossing_check accepted ONLY verdict=="PASS", so the
SKIPPED-CONDITION-only project fell through to "No CDC report found" → hard
FAIL → cascade-blocked all 25 downstream Phase-2/Phase-3 steps. Unlike
Steps 11/12/13/29/30 (#430/#436), Step 3 had no `cap:cdc` flag, so a known
tool gap was scored as a real failure.

Fix (programs/cdc_crossing_check.py): a CDC report whose verdict is
SKIPPED-CONDITION (a disclosed capability gap) is recognised explicitly and
treated as DEFERRED / WAIVED-DEFERRED — it carries the `cap:cdc` flag,
review_required (run a real CDC tool at sign-off), and PASSES the gate
(exit 0) so it does not block Phase 3.

ACCEPTANCE (#673): a multi-clock SKIPPED-CONDITION report → check passes as
DEFERRED/cap-gap (does not block phase3).

NEGATIVE no-leak (issue-mandated):
  * verdict=FAIL with real crossings → still a hard FAIL (a GENUINE CDC
    violation is never deferred, and DOMINATES even a PASS-shaped sibling).
  * no canonical report at all (and no tool *.rpt) → still FAIL ("No CDC
    report found") — only a DISCLOSED skip is deferred.
  * an unreadable / corrupt canonical JSON is NOT a disclosed skip → FAIL.
  * a legit single-clock PASS report → still PASS (unchanged; deferral moot).

chip-AGNOSTIC: keyed purely on the verdict tier (SKIPPED-CONDITION /
FAIL / PASS) and the runner's own canonical paths — no chip / vendor / SKU
literal. Verified by the field agent on the real benchmark before close.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import cdc_crossing_check as C  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
def _write_canonical(proj: Path, payload: dict) -> None:
    """Write the three runner-canonical CDC JSONs with the same payload,
    exactly as design_one_shot_runner does for the SKIPPED-CONDITION and
    no-RTL branches."""
    d = proj / "reports" / "phase2" / "cdc"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("crossing.json", "async_input.json", "reset_dep.json"):
        (d / name).write_text(json.dumps(payload))


def _multiclock_skip_payload() -> dict:
    # The exact shape design_one_shot_runner emits for a multi-clock design.
    return {
        "verdict": "SKIPPED-CONDITION",
        "reason": ("multi-clock design (root_clocks=['user_clock2', "
                   "'wb_clk_i'], scope: top): a real CDC tool run is "
                   "required — this runner does not synthesize crossing "
                   "verdicts (#436)"),
        "clocks_found": ["user_clock2", "wb_clk_i"],
        "posedge_tokens_all": ["user_clock2", "wb_clk_i"],
    }


# --------------------------------------------------------------------------
# ACCEPTANCE — disclosed SKIPPED-CONDITION cap-gap is DEFERRED, not a FAIL
# --------------------------------------------------------------------------
def test_multiclock_skipped_condition_is_deferred_pass(tmp_path):
    _write_canonical(tmp_path, _multiclock_skip_payload())
    res = C.audit_cdc(tmp_path)
    assert res.passed is True, "disclosed SKIPPED-CONDITION must not block"
    assert res.summary.get("cdc_skipped_condition") is True
    assert res.summary.get("deferred") is True
    assert res.summary.get("cap_flag") == "cap:cdc"


def test_deferred_finding_is_advisory_not_error(tmp_path):
    _write_canonical(tmp_path, _multiclock_skip_payload())
    res = C.audit_cdc(tmp_path)
    # No ERROR finding — it is an advisory capability-gap deferral.
    assert all(f.severity != "ERROR" for f in res.findings)
    cap = [f for f in res.findings if f.rule == "CDC_CAPABILITY_GAP_DEFERRED"]
    assert len(cap) == 1
    assert "cap:cdc" in cap[0].message
    assert "review_required" in cap[0].message
    # The named runner reason is surfaced for traceability.
    assert "multi-clock" in cap[0].message


def test_deferred_exit_code_is_zero(tmp_path):
    _write_canonical(tmp_path, _multiclock_skip_payload())
    out = tmp_path / "out.json"
    rc = C.main([str(tmp_path), "--json", str(out)])
    assert rc == 0, "WAIVED-DEFERRED must exit 0 so Phase 3 is not blocked"
    report = json.loads(out.read_text())
    assert report["passed"] is True
    assert report["summary"]["deferred"] is True


def test_no_rtl_skipped_condition_also_deferred(tmp_path):
    # The runner also emits SKIPPED-CONDITION (different reason) when a
    # project has no RTL — that is the same disclosed capability gap.
    _write_canonical(tmp_path, {
        "verdict": "SKIPPED-CONDITION",
        "reason": ("no RTL in this project — a CDC verdict cannot be "
                   "produced (#436: never emit another design's canned "
                   "crossings)"),
    })
    res = C.audit_cdc(tmp_path)
    assert res.passed is True
    assert res.summary.get("cap_flag") == "cap:cdc"
    assert res.summary.get("skip_reasons")  # reason surfaced


# --------------------------------------------------------------------------
# NEGATIVE no-leak — a GENUINE CDC violation still hard-FAILs
# --------------------------------------------------------------------------
def test_genuine_cdc_fail_with_crossings_still_fails(tmp_path):
    _write_canonical(tmp_path, {
        "verdict": "FAIL",
        "reason": "2 un-synchronized clock-domain crossings detected",
        "crossings": [
            {"from": "wb_clk_i", "to": "user_clock2", "signal": "data_q",
             "synchronized": False},
            {"from": "user_clock2", "to": "wb_clk_i", "signal": "ack",
             "synchronized": False},
        ],
        "clocks_found": ["user_clock2", "wb_clk_i"],
    })
    res = C.audit_cdc(tmp_path)
    assert res.passed is False, "a genuine CDC violation must hard-FAIL"
    assert any(f.severity == "ERROR" and f.rule == "CDC_VIOLATION"
               for f in res.findings)
    assert res.summary.get("genuine_cdc_fail") is True
    assert res.summary.get("deferred") is not True


def test_genuine_fail_exit_code_is_one(tmp_path):
    _write_canonical(tmp_path, {
        "verdict": "FAIL", "crossings": [{"signal": "x",
                                          "synchronized": False}]})
    rc = C.main([str(tmp_path)])
    assert rc == 1


def test_fail_dominates_a_pass_shaped_sibling(tmp_path):
    # If even ONE canonical report is a genuine FAIL, the gate must FAIL —
    # a real violation cannot be masked by a PASS-shaped sibling.
    d = tmp_path / "reports" / "phase2" / "cdc"
    d.mkdir(parents=True)
    (d / "crossing.json").write_text(json.dumps({
        "verdict": "FAIL",
        "crossings": [{"signal": "x", "synchronized": False}]}))
    (d / "async_input.json").write_text(json.dumps({
        "verdict": "PASS", "evidence": "single clock domain", "async_inputs": []}))
    (d / "reset_dep.json").write_text(json.dumps({
        "verdict": "PASS", "evidence": "single clock domain"}))
    res = C.audit_cdc(tmp_path)
    assert res.passed is False
    assert any(f.rule == "CDC_VIOLATION" for f in res.findings)


# --------------------------------------------------------------------------
# NEGATIVE no-leak — an actual MISSING report (not a disclosed skip) FAILs
# --------------------------------------------------------------------------
def test_no_report_at_all_still_fails(tmp_path):
    # Empty project: no canonical JSON, no tool *.rpt → "No CDC report found".
    res = C.audit_cdc(tmp_path)
    assert res.passed is False
    assert any(f.severity == "ERROR" and f.rule == "CDC_REPORT_EXISTS"
               for f in res.findings)
    assert res.summary.get("deferred") is not True


def test_corrupt_canonical_json_is_not_a_disclosed_skip(tmp_path):
    # An unreadable / corrupt canonical JSON must NOT masquerade as an honest
    # SKIPPED-CONDITION deferral — it is treated as absent → FAIL.
    d = tmp_path / "reports" / "phase2" / "cdc"
    d.mkdir(parents=True)
    for name in ("crossing.json", "async_input.json", "reset_dep.json"):
        (d / name).write_text("{ this is not valid json")
    res = C.audit_cdc(tmp_path)
    assert res.passed is False
    assert res.summary.get("deferred") is not True


def test_unknown_verdict_is_not_deferred(tmp_path):
    # A verdict the runner never emits (not PASS / FAIL / SKIPPED-CONDITION)
    # is not a disclosed cap-gap → must not be deferred; it falls through to
    # the missing-report / substance path and FAILs.
    _write_canonical(tmp_path, {"verdict": "MAYBE", "reason": "??"})
    res = C.audit_cdc(tmp_path)
    assert res.passed is False
    assert res.summary.get("deferred") is not True


# --------------------------------------------------------------------------
# Unchanged behaviour — a legit single-clock PASS still PASSes
# --------------------------------------------------------------------------
def test_single_clock_pass_unchanged(tmp_path):
    d = tmp_path / "reports" / "phase2" / "cdc"
    d.mkdir(parents=True)
    ev = ("clock-domain scan of 1 RTL file(s) [top]: single clock domain "
          "['clk'] — no clock-domain crossings exist")
    (d / "crossing.json").write_text(json.dumps({
        "verdict": "PASS", "evidence": ev, "crossings": [],
        "clocks_found": ["clk"]}))
    (d / "async_input.json").write_text(json.dumps({
        "verdict": "PASS", "evidence": ev, "async_inputs": []}))
    (d / "reset_dep.json").write_text(json.dumps({
        "verdict": "PASS", "evidence": ev, "clocks_found": ["clk"]}))
    res = C.audit_cdc(tmp_path)
    assert res.passed is True
    # A real PASS is NOT a deferral.
    assert res.summary.get("deferred") is not True


def test_classify_helper_directly(tmp_path):
    _write_canonical(tmp_path, _multiclock_skip_payload())
    c = C._classify_canonical_verdicts(tmp_path)
    assert c["disclosed_skip"] is True
    assert c["genuine_fail"] is False
    assert c["skip_reasons"] and "multi-clock" in c["skip_reasons"][0]
    assert len(c["present_paths"]) == 3
