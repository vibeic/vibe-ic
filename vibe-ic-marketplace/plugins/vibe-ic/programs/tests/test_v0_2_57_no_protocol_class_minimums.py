"""v0.2.57 no-protocol-class minimums regressions.

Pins the #428 fix (ORGANIC-20260606-structured-field-count-no-protocol-
class), both halves:

1. `l_doc_structured_field_count_check`: classes the registry marks
   `command_protocol_applicable=False` + `rtl_gen=null` (pure datapath /
   compute) have no source for opcodes / registers / OTP — the protocol
   minimums switch to an N/A-SKIPPED-CONDITION (L3/L6 skip; L4
   double-keyed on the doc HONESTLY recording zero content; L10/L13 fall
   back to a class-appropriate >=2 floor). bare_fpga / unknown stay
   fail-closed; protocol classes keep the strict minimums.

2. `bit_level_full_stack_tb_oracle_check`: vectors the harness ITSELF
   marks UNVERIFIED count in a disclosed bucket — not as functional
   fails — but ONLY while the documented connectivity-only waiver is
   active (never a silent green).

chip-AGNOSTIC: synthetic L-doc dicts + synthetic results.json fixtures.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import l_doc_structured_field_count_check as ldc  # noqa: E402
import bit_level_full_stack_tb_oracle_check as blc  # noqa: E402


# ── half 1: class-gated minimums ───────────────────────────────────────────

def test_registry_flag_classifies_datapath_classes():
    assert ldc._class_no_cmd_protocol("digital_arithmetic_primitive") is True
    assert ldc._class_no_cmd_protocol("processor_cpu") is True


def test_fail_closed_classes_never_relax():
    assert ldc._class_no_cmd_protocol("bare_fpga") is False
    assert ldc._class_no_cmd_protocol("unknown_protocol_class") is False


def test_protocol_class_keeps_strict_minimums():
    # a command-protocol class (registry flag True) keeps every floor
    assert ldc._class_no_cmd_protocol("digital_cmd_driven") is False
    ok, why = ldc._check_l_doc(3, {"opcodes": []},
                               ic_class="digital_cmd_driven")
    assert ok is False


def test_l3_na_needs_honest_empty_opcodes():
    # double-keyed per the #419 doctrine: the N/A requires the doc's OWN
    # honest `opcodes: []` — class flag alone is not enough
    ok, why = ldc._check_l_doc(3, {"opcodes": []},
                               ic_class="digital_arithmetic_primitive")
    assert ok is True, why
    # blob-only doc with NO opcodes key must keep failing (the gameable
    # chicken-egg: extraction failure degrades class detection, and a
    # missing key must never ride that into a silent N/A)
    ok, _ = ldc._check_l_doc(
        3, {"all_input_literals_aggregated": "blob"},
        ic_class="digital_arithmetic_primitive")
    assert ok is False


def test_l6_stays_a_floor_not_a_skip():
    # per the filing, FSM minimums FALL BACK to a class floor (>=2) — zero
    # FSM states must STILL fail even for a no-protocol datapath class.
    ok, _ = ldc._check_l_doc(6, {"fsm_states": []},
                             ic_class="digital_arithmetic_primitive")
    assert ok is False


def test_l4_na_only_when_doc_honestly_empty():
    # honestly-zero registers (EXPLICIT empty list) on a no-protocol
    # class -> N/A
    ok, _ = ldc._check_l_doc(4, {"registers": []},
                             ic_class="digital_arithmetic_primitive")
    assert ok is True
    # PARTIAL content proves a source exists -> floor stays (extraction gap)
    ok, why = ldc._check_l_doc(
        4, {"registers": [{"name": "ctrl", "addr": 0}]},
        ic_class="digital_arithmetic_primitive")
    assert ok is False and "≥5" in why
    # blob-only doc with NO registers key at all keeps failing
    ok, _ = ldc._check_l_doc(
        4, {"all_input_literals_aggregated": "blob"},
        ic_class="digital_arithmetic_primitive")
    assert ok is False


def test_l4_strict_for_protocol_class():
    ok, _ = ldc._check_l_doc(4, {"registers": []},
                             ic_class="digital_cmd_driven")
    assert ok is False


def test_l10_l13_class_appropriate_floor():
    two_cases = {"test_cases": [{"n": 1}, {"n": 2}]}
    ok, _ = ldc._check_l_doc(10, two_cases,
                             ic_class="digital_arithmetic_primitive")
    assert ok is True
    ok, _ = ldc._check_l_doc(10, two_cases, ic_class="digital_cmd_driven")
    assert ok is False
    ok, _ = ldc._check_l_doc(13, two_cases,
                             ic_class="digital_arithmetic_primitive")
    assert ok is True


# ── half 2: UNVERIFIED vectors are a disclosed bucket under the waiver ────

def _project(tmp_path, with_waiver: bool, per_vector, vt, vp):
    proj = tmp_path / "proj"
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    sim.mkdir(parents=True)
    results = {
        "vectors_total": vt, "vectors_passed": vp,
        "vectors_failed": vt - vp,
        "per_vector": per_vector,
        "input_doc_evidence": "L10_TEST_CASES.json#cases (synthetic fixture)",
    }
    rp = sim / "results.json"
    rp.write_text(json.dumps(results))
    if with_waiver:
        (proj / "waivers.json").write_text(json.dumps({
            blc.WAIVER_KEY_CONNECTIVITY:
                "connectivity-only skeleton TB; functional vectors are "
                "placeholders pending a golden source (documented waiver, "
                "more than forty characters of justification here)."}))
    return proj, rp


def _vec(name, verdict, expected="aa"):
    return {"name": name, "verdict": verdict,
            "expected_bytes": expected, "actual_bytes": expected}


def test_unverified_bucket_with_waiver_is_warn_not_fail(tmp_path):
    pv = ([_vec(f"v{i}", "PASS") for i in range(6)]
          + [_vec("c1", "UNVERIFIED", "XX"), _vec("c2", "UNVERIFIED", "XX")])
    proj, rp = _project(tmp_path, True, pv, vt=8, vp=6)
    out = blc.check(proj, rp)
    f_rules = [f["rule"] for f in out["findings"]]
    w_rules = [w["rule"] for w in out["warnings"]]
    assert "VECTORS_NOT_ALL_PASS" not in f_rules
    assert "VECTORS_UNVERIFIED_CONNECTIVITY_ONLY" in w_rules
    assert out["vectors_unverified"] == 2


def test_unverified_without_waiver_still_fails(tmp_path):
    pv = ([_vec(f"v{i}", "PASS") for i in range(6)]
          + [_vec("c1", "UNVERIFIED", "XX"), _vec("c2", "UNVERIFIED", "XX")])
    proj, rp = _project(tmp_path, False, pv, vt=8, vp=6)
    out = blc.check(proj, rp)
    assert "VECTORS_NOT_ALL_PASS" in [f["rule"] for f in out["findings"]]


def test_real_vector_fails_not_masked_by_waiver(tmp_path):
    # a REAL FAIL vector (not harness-marked UNVERIFIED) must keep failing
    # even when the connectivity waiver is active
    pv = ([_vec(f"v{i}", "PASS") for i in range(6)]
          + [_vec("bad", "FAIL"), _vec("c1", "UNVERIFIED", "XX")])
    proj, rp = _project(tmp_path, True, pv, vt=8, vp=6)
    out = blc.check(proj, rp)
    assert "VECTORS_NOT_ALL_PASS" in [f["rule"] for f in out["findings"]]
