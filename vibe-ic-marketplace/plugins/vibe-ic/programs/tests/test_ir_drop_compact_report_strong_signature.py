"""The ir_drop size-floor false-positive: a genuinely-real but COMPACT
OpenROAD PSM `analyze_power_grid` summary JSON was rejected as a "hand-typed
stub" because STRONG_SIGNATURE_GROUPS carried entries for `sta` and `lvs`
(added v1.3.94 for exactly this small-design shape) but never for `ir_drop`,
which shares the SAME 1024 B floor (MIN_REPORT_BYTES["ir_drop"]).

Measured motivation: 16 of 16 authentic openroad-psm ir_drop.json across
benchmark-data are <1024 B (197-611 B), so the floor false-rejected every one.

chip-AGNOSTIC — no chip / pin / net / vendor / node literal (VDD is a
universal power rail).

Bidirectional negative control (the point of this file):
  * FORWARD: an authentic compact PSM ir_drop.json (<1024 B, carrying the
    producer triple) must NOT raise IR_DROP_REPORT_TOO_SMALL. This assertion
    FAILS against the byte-identical pre-fix eda_report_audit.py (no `ir_drop`
    strong group) and PASSES after the fix.
  * REVERSE (must STILL fail both before and after): a genuine hand-typed stub
    (<1024 B, WITHOUT the producer triple) must STILL raise
    IR_DROP_REPORT_TOO_SMALL. This is what proves the fix waives the floor for
    real output ONLY — it does not swallow the defect the floor exists to
    catch.
"""
import importlib

audit = importlib.import_module("eda_report_audit")


# A real-but-compact OpenROAD PSM summary — the producer's self-identifying
# output (same shape the runner emits; matches benchmark-data corpus).
_AUTHENTIC_COMPACT = """{
  "tool": "openroad-psm",
  "mode": "static_ir_drop",
  "power_nets": ["VDD"],
  "source": "reports/phase3/ir_drop.rpt",
  "worst_ir_uv": 55000.0,
  "worst_ir_pct_vdd": 3.056,
  "budget_uv": 180000.0,
  "verdict": "PASS",
  "evidence": "analyze_power_grid stdout"
}"""

# A hand-typed stub. It carries an ir_drop tool-signature word ("IR drop") so
# it is NOT rejected merely for lacking a signature — it is undersized AND has
# none of the producer triple. This is the 2026-04-22 "sums violations: 0"
# shape the size floor was added to catch.
_HAND_TYPED_STUB = '{"note": "IR drop analysis clean", "violations": 0}'


def _run(tmp_path, body):
    f = tmp_path / "ir_drop.json"
    f.write_text(body)
    res = audit.AuditResult(program="t", passed=False)
    ok = audit._check_tool_authenticity([f], "ir_drop", res)
    rules = {x.rule for x in res.findings}
    return ok, rules


def test_authentic_compact_ir_drop_not_flagged_too_small(tmp_path):
    # FORWARD — fails on pre-fix code, passes after the fix.
    assert len(_AUTHENTIC_COMPACT.encode()) < 1024
    ok, rules = _run(tmp_path, _AUTHENTIC_COMPACT)
    assert "IR_DROP_REPORT_TOO_SMALL" not in rules, (
        "an authentic compact PSM ir_drop.json must not be called a stub")
    assert ok is True


def test_hand_typed_ir_drop_stub_still_rejected(tmp_path):
    # REVERSE — must STILL fail after the fix (no over-loosening).
    assert len(_HAND_TYPED_STUB.encode()) < 1024
    ok, rules = _run(tmp_path, _HAND_TYPED_STUB)
    assert "IR_DROP_REPORT_TOO_SMALL" in rules, (
        "a hand-typed stub with no producer signature must still be caught")
    assert ok is False


def test_strong_signature_helper_ir_drop_direct():
    # Direct unit on the helper the fix wires in.
    assert audit._has_strong_signature(_AUTHENTIC_COMPACT, "ir_drop") is True
    assert audit._has_strong_signature(_HAND_TYPED_STUB, "ir_drop") is False


def test_reverse_sta_lvs_groups_unchanged():
    # The pre-existing sta / lvs strong groups must be untouched by the fix.
    assert "sta" in audit.STRONG_SIGNATURE_GROUPS
    assert "lvs" in audit.STRONG_SIGNATURE_GROUPS
    assert audit._has_strong_signature(
        "Startpoint ... Endpoint ... slack 0.12", "sta") is True
