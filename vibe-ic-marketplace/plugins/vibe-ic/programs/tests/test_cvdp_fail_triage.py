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
sys.path.insert(0, str(PLUGIN / "benchmark-harness"))
import cvdp_fail_triage as T  # noqa: E402

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
    assert T.classify_log("Cleaning up Docker resources...") == "UNKNOWN"


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
    real = Path("/home/reyerchu/AI_IC_design/cvdp_open_run_v0325"
                "/work_score/raw_result.json")
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
    assert set(d["mode_summary"]) <= {"SYNTH_GATE", "ELAB_ERROR",
                                      "FUNC_PARTIAL", "FUNC_ALL", "UNKNOWN"}


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
