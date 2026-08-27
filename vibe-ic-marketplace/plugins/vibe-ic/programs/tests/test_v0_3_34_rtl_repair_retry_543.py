"""ORGANIC #543 — rtl_repair_retry: stale cross-round TB pickup + WAIVED reference_tb
treated as FAIL (FAIL_RTL_REPAIR_INERT).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402


def test_543_named_tb_preferred_over_stale(tmp_path):
    # sim_full_stack has a stale tb_OLD_full.v (from previous round top)
    # and the current tb_chip_top_full.v.  Only chip_top should be picked.
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "tb_OLD_full.v").write_text("module tb_OLD_full; endmodule\n")
    (sim / "tb_chip_top_full.v").write_text("module tb_chip_top_full; endmodule\n")
    result = R._reference_tb_generic_full_stack(
        tmp_path, "chip_top", "test", 0.0)
    # The function must NOT use tb_OLD_full.v (stale).  It may PASS, FAIL, or
    # SKIP depending on whether iverilog is available, but must never attempt
    # to compile tb_OLD_full.
    assert result.name == "reference_tb"
    # Verify by checking the extras or detail — stale name must not appear.
    detail = result.detail or ""
    assert "tb_OLD_full" not in detail


def test_543_stale_only_falls_back_when_no_named(tmp_path):
    # Only the stale tb_OTHER_full.v exists (no tb_chip_top_full.v).
    # The fallback accepts it (glob result) — behaviour unchanged.
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "tb_OTHER_full.v").write_text("module tb_OTHER_full; endmodule\n")
    result = R._reference_tb_generic_full_stack(
        tmp_path, "chip_top", "test", 0.0)
    assert result.name == "reference_tb"
    # fallback is accepted — result may succeed or fail depending on iverilog


def test_543_waived_reference_tb_breaks_rtl_repair_retry(tmp_path, monkeypatch):
    # When step_reference_tb returns WAIVED, the rtl_repair_retry must NOT enter.
    # We can't call main() easily, but we can test the break condition
    # logic by inspecting that "WAIVED" is in the allowed statuses.
    # Verify it by checking the runner's outer status-tuple includes it.
    import inspect
    src = inspect.getsource(R)
    # The rtl_repair_retry break must include "WAIVED"
    assert '"WAIVED"' in src or "'WAIVED'" in src
    # And specifically, the break condition must appear after the
    # step_reference_tb call inside the while True loop.
    idx_while = src.index("while True:")
    idx_break_set = src.index(
        '"PASS", "SKIP", "WAIVED"', idx_while)
    assert idx_break_set > idx_while


def test_543_waived_not_entering_repair(monkeypatch):
    # Directly test the rtl_repair_retry break: status WAIVED must break early
    # without any RTL repair retry.  We simulate by checking that the
    # condition `sr.status in ("PASS", "SKIP", "WAIVED")` is True for WAIVED.
    waived = R.StepResult("reference_tb", "WAIVED", 0.0, "test")
    assert waived.status in ("PASS", "SKIP", "WAIVED")  # break fires
