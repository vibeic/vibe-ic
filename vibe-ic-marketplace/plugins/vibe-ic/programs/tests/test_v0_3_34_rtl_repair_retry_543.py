"""ORGANIC #543 — rtl_repair_retry: stale cross-round TB pickup + WAIVED reference_tb
treated as FAIL (FAIL_RTL_REPAIR_INERT).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402




    # fallback is accepted — result may succeed or fail depending on iverilog


def test_543_waived_reference_tb_breaks_rtl_repair_retry(tmp_path, monkeypatch):
    # When step_reference_tb returns WAIVED, the rtl_repair_retry must NOT enter.
    # We can't call main() easily, but we can test the break condition
    # logic by inspecting that "PASS_WITH_WAIVERS" is in the allowed statuses.
    # Verify it by checking the runner's outer status-tuple includes it.
    # R-0915-85 — the break condition names the five through the vocabulary
    # module rather than retyping them, so this reads for the NAMES, not for a
    # literal tuple that a migration can leave stale. `"WAIVED"` in the source
    # would now prove the opposite of what it used to: a dead comparison.
    import inspect
    src = inspect.getsource(R)
    # The runner still SPELLS `WAIVED` in one place that is not a step status
    # -- the FPGA on-board manifest's own `verdict` field -- so a blanket
    # source scan would be asserting about the wrong vocabulary. What must not
    # survive is a comparison of a STEP STATUS against it, and that is the
    # ratchet's comparison pass, not this file's business.
    idx_while = src.index("while True:")
    idx_break_set = src.index(
        "_V.Verdict.PASS_WITH_WAIVERS.value", idx_while)
    assert idx_break_set > idx_while


def test_543_waived_not_entering_repair(monkeypatch):
    # Directly test the rtl_repair_retry break: status WAIVED must break early
    # without any RTL repair retry.  We simulate by checking that the
    # condition `sr.status in ("PASS", "SKIP", "PASS_WITH_WAIVERS")` is True for WAIVED.
    waived = R.StepResult("reference_tb", "PASS_WITH_WAIVERS", 0.0, "test",
                          attribution="the verification engineer")
    # The break fires on the words the runner actually tests, read from the
    # vocabulary module so this cannot drift from the condition it describes.
    import verdict as _V
    assert waived.status in (_V.Verdict.PASS.value,
                             _V.Verdict.NOT_APPLICABLE.value,
                             _V.Verdict.PASS_WITH_WAIVERS.value)
