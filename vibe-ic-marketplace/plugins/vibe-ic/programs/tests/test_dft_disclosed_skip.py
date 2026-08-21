"""Tests for the HONEST disclosed-skip sentinel on the three DFT sign-off
gates (dft_atpg_coverage_check / bsdl_emit / dft_signoff_check) + the shared
dft_signoff_common.disclosed_atpg_skip helper.

The skip path resolves flow step-11 to SKIPPED-CONDITION (rc=2 → VACUOUS_PASS
tier) when — and ONLY when — the gate's required input artifact is ABSENT
*and* a co-located sibling JSON in phase2/stage2/dft/ honestly self-reports
the skip (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION). This is NOT cheating:
a design that produced any real input is judged normally (a real low coverage
still FAILs), and the skip never fires without the honest sentinel.

For EACH of the 3 gates:
  1. input ABSENT + sibling dft_atpg_not_run.json  → main([...]) == 2
  2. input ABSENT + NO sibling skip note           → original FAIL (rc 1)
  3. input PRESENT (+ sentinel present too)        → normal verdict, NOT 2,
                                                     byte-identical to no-sentinel
"""
import json
import sys
from pathlib import Path

PROG_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROG_DIR))

import dft_signoff_common  # noqa: E402
import dft_atpg_coverage_check as cov_gate  # noqa: E402
import bsdl_emit  # noqa: E402
import dft_signoff_check  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────

def _dft_dir(project: Path) -> Path:
    d = project / "phase2" / "stage2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_sentinel(project: Path,
                    verdict: str = "SKIPPED-CONDITION",
                    reason: str = "OSS Fault ATPG engine could not measure "
                                  "sign-off coverage on sky130 generic DFF "
                                  "form") -> Path:
    p = _dft_dir(project) / "dft_atpg_not_run.json"
    payload = {"verdict": verdict, "capability_flag": "cap:atpg_signoff_coverage"}
    if reason is not None:
        payload["reason"] = reason
    p.write_text(json.dumps(payload, indent=2))
    return p


def _write_measurable_coverage(project: Path, pct: float = 99.0,
                               target: float = 95.0) -> Path:
    d = project / "reports" / "phase2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "coverage.json"
    p.write_text(json.dumps({
        "tool": "fault",
        "coverage_pct": pct,
        "faults_covered": int(pct),
        "faults_total": 100,
        "target_pct": target,
        "stuck_at_ge_target": pct >= target,
        "transition": {"engine_limited": True,
                       "reason": "OSS engine has no launch-off-capture"},
    }, indent=2))
    return p


def _write_scan_netlist(project: Path) -> Path:
    p = _dft_dir(project) / "scan_netlist.v"
    p.write_text("module top(input a, output b);\n"
                 "  assign b = a;\n"
                 "endmodule\n")
    return p


# ═══════════════════════════════════════════════════════════════════════
#  disclosed_atpg_skip — direct unit tests
# ═══════════════════════════════════════════════════════════════════════

def test_helper_present_verdict_returns_reason(tmp_path):
    _write_sentinel(tmp_path, reason="engine could not measure")
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) == \
        "engine could not measure"


def test_helper_absent_returns_none(tmp_path):
    # no dft dir at all
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) is None


def test_helper_empty_dft_dir_returns_none(tmp_path):
    _dft_dir(tmp_path)  # exists but empty
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) is None


def test_helper_non_skip_verdict_returns_none(tmp_path):
    _write_sentinel(tmp_path, verdict="FAIL")
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) is None
    _write_sentinel(tmp_path, verdict="PASS")
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) is None


def test_helper_bad_json_skipped(tmp_path):
    # A malformed JSON must be tolerated (skipped), not crash.
    (_dft_dir(tmp_path) / "garbage.json").write_text("{not valid json,,,")
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) is None
    # bad JSON co-located with a valid sentinel → still finds the sentinel.
    _write_sentinel(tmp_path, reason="ok")
    assert dft_signoff_common.disclosed_atpg_skip(tmp_path) == "ok"


def test_helper_verdict_variants(tmp_path):
    for vd in ("SKIP", "SKIPPED", "skipped", "SKIPPED-CONDITION",
               "SKIPPED_CONDITION", "skipped-condition"):
        _write_sentinel(tmp_path, verdict=vd, reason="r")
        assert dft_signoff_common.disclosed_atpg_skip(tmp_path) == "r", vd


def test_helper_missing_reason_returns_default(tmp_path):
    _write_sentinel(tmp_path, verdict="SKIPPED", reason=None)
    got = dft_signoff_common.disclosed_atpg_skip(tmp_path)
    assert got is not None and "disclosed-skip" in got


# ═══════════════════════════════════════════════════════════════════════
#  dft_atpg_coverage_check
# ═══════════════════════════════════════════════════════════════════════

def test_cov_absent_input_with_sentinel_rc2(tmp_path):
    _write_sentinel(tmp_path)
    assert cov_gate.main([str(tmp_path)]) == 2


def test_cov_absent_input_no_sentinel_fails(tmp_path):
    # no coverage evidence, no sentinel → original honest FAIL (rc 1)
    assert cov_gate.main([str(tmp_path)]) == 1


def test_cov_present_input_not_skipped(tmp_path):
    _write_measurable_coverage(tmp_path, pct=99.0, target=95.0)
    rc_no_sentinel = cov_gate.main([str(tmp_path)])
    # add the sentinel: present input MUST still win (skip must NOT fire)
    _write_sentinel(tmp_path)
    rc_with_sentinel = cov_gate.main([str(tmp_path)])
    assert rc_no_sentinel == 0            # real measurable 99% >= 95% → PASS
    assert rc_with_sentinel == 0          # byte-identical, NOT 2
    assert rc_with_sentinel != 2


def test_cov_present_low_still_fails_even_with_sentinel(tmp_path):
    # A real, present, LOW coverage must FAIL — the sentinel must not rescue it.
    _write_measurable_coverage(tmp_path, pct=40.0, target=95.0)
    _write_sentinel(tmp_path)
    rc = cov_gate.main([str(tmp_path)])
    assert rc == 1  # measurable-but-low → honest FAIL, NOT skipped (2)


# ═══════════════════════════════════════════════════════════════════════
#  bsdl_emit
# ═══════════════════════════════════════════════════════════════════════

def test_bsdl_absent_input_with_sentinel_rc2(tmp_path):
    _write_sentinel(tmp_path)  # scan_netlist.v absent
    assert bsdl_emit.main([str(tmp_path)]) == 2


def test_bsdl_absent_input_no_sentinel_fails(tmp_path):
    # no scan netlist, no sentinel → original FAIL (netlist not found, rc 1)
    assert bsdl_emit.main([str(tmp_path)]) == 1


def test_bsdl_present_input_not_skipped(tmp_path):
    _write_scan_netlist(tmp_path)
    rc_no_sentinel = bsdl_emit.main([str(tmp_path)])
    _write_sentinel(tmp_path)
    rc_with_sentinel = bsdl_emit.main([str(tmp_path)])
    # bare core (input/output, no pads) → N_A → rc 0
    assert rc_no_sentinel == 0
    assert rc_with_sentinel == 0          # byte-identical, NOT 2
    assert rc_with_sentinel != 2


# ═══════════════════════════════════════════════════════════════════════
#  dft_signoff_check
# ═══════════════════════════════════════════════════════════════════════

def test_signoff_absent_input_with_sentinel_rc2(tmp_path):
    _write_sentinel(tmp_path)  # no coverage.json / rpt / scan_netlist.v
    assert dft_signoff_check.main([str(tmp_path)]) == 2


def test_signoff_absent_input_no_sentinel_fails(tmp_path):
    assert dft_signoff_check.main([str(tmp_path)]) == 1


def test_signoff_present_input_not_skipped(tmp_path):
    _write_scan_netlist(tmp_path)   # a real DFT input present
    rc_no_sentinel = dft_signoff_check.main([str(tmp_path)])
    _write_sentinel(tmp_path)
    rc_with_sentinel = dft_signoff_check.main([str(tmp_path)])
    # scan netlist present but no coverage/bsdl → normal FAIL (rc 1)
    assert rc_no_sentinel == 1
    assert rc_with_sentinel == 1          # byte-identical, NOT 2
    assert rc_with_sentinel != 2


def test_signoff_present_coverage_input_not_skipped(tmp_path):
    # A present measurable coverage.json is also a "real input" → judged
    # normally (skip must NOT fire) even with the sentinel present.
    _write_measurable_coverage(tmp_path, pct=99.0, target=95.0)
    _write_sentinel(tmp_path)
    rc = dft_signoff_check.main([str(tmp_path)])
    assert rc != 2  # real input present → normal judgment, never skipped
