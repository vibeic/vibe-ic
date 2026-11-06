"""Regression coverage for #3420 and #3421."""
import sys
from pathlib import Path
from types import SimpleNamespace

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import lec_run as LR  # noqa: E402


class _Proc:
    def __init__(self, rc, out):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def test_same_invocation_preflight_names_unmounted_input(monkeypatch):
    seen = {}

    def wrap(cmd, seconds):
        seen.update(cmd=cmd, seconds=seconds)
        return cmd

    monkeypatch.setattr(
        LR, "_dw_mod",
        lambda: SimpleNamespace(wrap_with_container_timeout=wrap))
    monkeypatch.setattr(
        LR, "_docker",
        lambda *a, **k: _Proc(
            125, LR._EXECUTION_INPUT_UNREACHABLE_PREFIX +
            "/mnt/ssd2/project/reports/lec_equiv.ys\n"))

    launched, raw = LR.run_yosys_equiv(
        "vibeic-eda", "/mnt/ssd2/project/reports/lec_equiv.ys",
        timeout=31,
        required_paths=["/mnt/ssd2/project/reports/lec_equiv.ys",
                        "/mnt/ssd2/project/rtl/top.v"],
        required_dirs=["/mnt/ssd2/project"])

    assert launched is False
    assert "test -r /mnt/ssd2/project/reports/lec_equiv.ys" in seen["cmd"]
    assert "test -r /mnt/ssd2/project/rtl/top.v" in seen["cmd"]
    assert "test -d /mnt/ssd2/project" in seen["cmd"]
    assert LR.execution_input_missing_paths(raw) == [
        "/mnt/ssd2/project/reports/lec_equiv.ys"]




def test_real_mismatch_is_unchanged_fail():
    parsed = LR.parse_equiv_output(
        "Yosys 0.68\nFound 2 $equiv cells in equiv:\n"
        "  Of those cells 1 are proven and 1 are unproven.\n")
    assert parsed["verdict"] == "FAIL"
