"""ORGANIC #534 — cvdp_fail_triage: mechanical log→mode classification with
fixed blind-safe hints.

Synthetic fixtures pin each mode signature (durable assertions); the real
on-host run is checked CONTENT-gated (live-corpus doctrine).
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_fail_triage as T  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

SYNTH_LOG = """\
>           value_after  = stats_after[f"Number of {key}"]
E           KeyError: 'Number of cells'
/src/synth.py:70: KeyError
FAILED ../../src/synth.py::test_yosys - KeyError: 'Number of cells'
"""

ELAB_LOG = """\
rtl/dut.sv:12: syntax error
I give up.
"""

FUNC_PARTIAL_LOG = "Failed 1 of 10 tests\n"
FUNC_ALL_LOG = "Failed 10 of 10 tests\n"


def test_mode_signatures():
    assert T.classify_log(SYNTH_LOG) == "SYNTH_GATE"
    assert T.classify_log(ELAB_LOG) == "ELAB_ERROR"
    assert T.classify_log(FUNC_PARTIAL_LOG) == "FUNC_PARTIAL"
    assert T.classify_log(FUNC_ALL_LOG) == "FUNC_ALL"
    # a log with NO verdict evidence at all is the TRUNCATED infra shape
    # (field round-2), not "unclassifiable".
    assert T.classify_log("Cleaning up Docker resources...") == "TRUNCATED"


def test_hints_are_blind_safe():
    # the hint table is FIXED and convention-level: no hint may carry an
    # oracle expectation shape (hex constants, == comparisons, signal==value).
    for mode, hint in T.HINTS.items():
        assert "==" not in hint and "0x" not in hint.lower(), (mode, hint)


def _mk_run(tmp_path, logs):
    """Build a synthetic raw_result + reports tree.
    logs: {pid: (result_code, log_text)}"""
    raw = {}
    for pid, (rc, text) in logs.items():
        prob_dir = tmp_path / pid.rsplit("_", 1)[0] / "reports"
        prob_dir.mkdir(parents=True, exist_ok=True)
        lp = prob_dir / "1.txt"
        lp.write_text(text)
        raw[pid] = {"category": "cid003", "difficulty": "easy",
                    "tests": [{"result": rc, "log": str(lp),
                               "error_msg": None}], "errors": 0}
    rp = tmp_path / "raw_result.json"
    rp.write_text(json.dumps(raw))
    return rp


def test_cli_end_to_end(tmp_path):
    rp = _mk_run(tmp_path, {
        "p_synth_0001": (1, SYNTH_LOG),
        "p_elab_0001": (1, ELAB_LOG),
        "p_part_0001": (1, FUNC_PARTIAL_LOG),
        "p_all_0001": (1, FUNC_ALL_LOG),
        "p_pass_0001": (0, "all good"),
    })
    out = tmp_path / "triage.json"
    rc = T.main(["--raw", str(rp), "--out", str(out)])
    assert rc == 0
    d = json.loads(out.read_text())
    assert d["total_fails"] == 4                      # the pass is excluded
    modes = {r["id"]: r["mode"] for r in d["records"]}
    assert modes == {"p_synth_0001": "SYNTH_GATE",
                     "p_elab_0001": "ELAB_ERROR",
                     "p_part_0001": "FUNC_PARTIAL",
                     "p_all_0001": "FUNC_ALL"}
    assert all(r["blind_safe_hint"] for r in d["records"])


def test_real_run_classifies_when_present(tmp_path):
    # live-corpus doctrine: content-gated, never existence-gated.
    real = require_corpus("cvdp_open_run_v0325/work_score/raw_result.json")
    if not real.is_file():
        pytest.skip("real CVDP run not on this host")
    raw = json.loads(real.read_text(errors="replace"))
    fails = [pid for pid, info in raw.items()
             if any(t.get("result") not in (0, "0", None)
                    for t in (info.get("tests") or []))]
    if not fails:
        pytest.skip("real run currently has no failing record")
    out = tmp_path / "triage.json"
    rc = T.main(["--raw", str(real), "--out", str(out)])
    assert rc == 0
    d = json.loads(out.read_text())
    assert d["total_fails"] == len(fails)
    assert set(d["mode_summary"]) <= {"SYNTH_GATE", "SYNTH_THRESHOLD",
                                      "ELAB_ERROR", "FUNC_PARTIAL",
                                      "FUNC_ALL", "TRUNCATED", "UNKNOWN"}


# ── adversarial-review round-2 regressions ─────────────────────────────────

def test_review2_pytest_bottomline_separates_partial_from_all():
    # HIGH (review): the dominant CVDP shape prints 'Failed 1 of 1 tests'
    # per invocation — only the pytest bottom-line separates partial/all.
    partial = ("ERROR: Failed 1 of 1 tests.\n"
               "=========== 1 failed, 8 passed in 12.3s ===========\n")
    allfail = ("ERROR: Failed 1 of 1 tests.\n"
               "ERROR: Failed 1 of 1 tests.\n"
               "=========== 2 failed in 9.9s ===========\n")
    assert T.classify_log(partial) == "FUNC_PARTIAL"
    assert T.classify_log(allfail) == "FUNC_ALL"


def test_review2_elab_anchored_not_coincidental_error_token():
    # LOW (review): 'AssertionError: …' in a functional log must NOT flip
    # the mode to ELAB_ERROR; a real iverilog CalledProcessError must.
    func_log = ("AssertionError: expected behavior mismatch\n"
                "=========== 3 failed in 1s ===========\n")
    assert T.classify_log(func_log) == "FUNC_ALL"
    compile_kill = ("subprocess.CalledProcessError: Command '['iverilog', "
                    "'-o', 'sim.vvp', 'rtl/dut.sv']' returned non-zero\n")
    assert T.classify_log(compile_kill) == "ELAB_ERROR"


# ── field round-2 reopen regressions (#534) ────────────────────────────────

FLAGSHIP_LOG = """\
** TESTS=10 PASS=9 FAIL=1 SKIP=0                       1639.00  0.02 **
ERROR    Icarus:runner.py:572 ERROR: Failed 1 of 10 tests.
============================== 1 failed in 0.42s ===============================
"""


def test_round2_flagship_cocotb_summary_is_partial():
    # the field's flagship counter-evidence: TESTS=10 PASS=9 FAIL=1 must be
    # FUNC_PARTIAL — the pytest bottom line ("1 failed") wraps the whole
    # cocotb run as ONE test and must not override per-test granularity.
    assert T.classify_log(FLAGSHIP_LOG) == "FUNC_PARTIAL"


def test_round2_func_all_requires_zero_pass_evidence():
    # 10 invocations all TESTS=1 PASS=0 FAIL=1 (the real MSHR shape) → ALL;
    # in-flight prose like "Diagnostic bus checks passed." is NOT a verdict.
    allfail = ("** TESTS=1 PASS=0 FAIL=1 SKIP=0 **\n" * 10
               + "  255.00ns INFO  cocotb.x  Mode 0: Diagnostic bus checks "
                 "passed.\n"
               + "=========== 10 failed in 9s ===========\n")
    assert T.classify_log(allfail) == "FUNC_ALL"


def test_round2_synth_threshold_mode():
    log = ('            print("No upgrades in synthesis: Errors detected '
           'in the after log. Synthesis failed.")\n'
           "FAILED ../../src/synth.py::test_yosys - AssertionError: "
           "Optimization failed: ...\n")
    assert T.classify_log(log) == "SYNTH_THRESHOLD"


def test_round2_truncated_midrun_log():
    # the real truncated shape: in-flight cocotb lines, no summary of any
    # family, cut before verdict.
    log = ("   410.00ns INFO  cocotb.regression  test_a passed\n"
           "   410.00ns INFO  cocotb.regression  running test_b (2/10)\n")
    assert T.classify_log(log) == "TRUNCATED"


def test_round2_problem_level_passing_tests_force_partial(tmp_path):
    # the failing invocation's log says all-fail, but the problem has
    # PASSING sibling tests in raw_result → FUNC_PARTIAL by definition.
    rp = _mk_run(tmp_path, {"p_mix_0001": (1, FUNC_ALL_LOG)})
    raw = json.loads(rp.read_text())
    # add a passing sibling test to the same problem
    raw["p_mix_0001"]["tests"].append(
        {"result": 0, "log": None, "error_msg": None})
    rp.write_text(json.dumps(raw))
    out = tmp_path / "t.json"
    assert T.main(["--raw", str(rp), "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["records"][0]["mode"] == "FUNC_PARTIAL"


def test_round2_real_final_run_flagship_and_truncated(tmp_path):
    # content-gated real-run pins: the flagship record classifies PARTIAL
    # and the 4 host-confirmed TRUNCATED records classify TRUNCATED.
    real = require_corpus("cvdp_open_run_v0325/work_score_final/raw_result.json")
    if not real.is_file():
        pytest.skip("real final run not on this host")
    out = tmp_path / "t.json"
    rc = T.main(["--raw", str(real), "--reports",
                 str(real.parent), "--out", str(out)])
    assert rc == 0
    d = json.loads(out.read_text())
    m = {r["id"]: r["mode"] for r in d["records"]}
    flag = m.get("cvdp_copilot_64b66b_decoder_0011")
    if flag is not None:
        assert flag == "FUNC_PARTIAL"
    assert d["mode_summary"].get("TRUNCATED", 0) >= 1
