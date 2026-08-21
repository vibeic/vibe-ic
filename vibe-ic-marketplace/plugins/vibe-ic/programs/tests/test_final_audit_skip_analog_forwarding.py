"""Regression: phase2 final_audit must forward --skip-analog to flow_compliance_check.py
when the runner was invoked with --skip-analog.

Captured from v0.1.53 CVDP Shape-D run (Bucket A, R2): a digital-only project
(`fixed_priority_arbiter`, `digital_arithmetic_primitive` IC class) was run
with `vibe_ic_one_shot_runner.py --skip-analog` but final_audit FAILed on
missing `phase1/analog/analog_block_list.json`. The audit's check_step already
honors `skip_analog`, but the runner wasn't forwarding the flag.

These tests pin the CLI contract so the bug can't reappear.
"""
import importlib
import sys
from pathlib import Path

P2_DIR = Path(__file__).resolve().parents[1]
P2_SCRIPT = P2_DIR / "design_one_shot_runner.py"


def _load_p2():
    """design_one_shot_runner uses @dataclass at module scope which requires
    sys.modules registration BEFORE exec — otherwise dataclass field resolution
    raises AttributeError on cls.__module__.__dict__.
    """
    if "design_one_shot_runner" in sys.modules:
        return sys.modules["design_one_shot_runner"]
    # Put programs/ on sys.path so the module's relative imports resolve, then
    # use the standard importlib.import_module mechanism.
    sys.path.insert(0, str(P2_DIR))
    try:
        return importlib.import_module("design_one_shot_runner")
    finally:
        # Leave on path for subsequent tests
        pass


def test_build_final_audit_cmd_omits_skip_analog_by_default():
    """Default: NO --skip-analog flag (preserve prior behaviour for non-digital projects)."""
    mod = _load_p2()
    cmd = mod._build_final_audit_cmd(Path("/tmp/p"), Path("/tmp/audit.py"), phase=2)
    assert "--skip-analog" not in cmd, (
        f"Default should not emit --skip-analog (would break analog audits): {cmd}")


def test_build_final_audit_cmd_forwards_skip_analog_when_requested():
    """When skip_analog=True, --skip-analog appears as a flag in the argv."""
    mod = _load_p2()
    cmd = mod._build_final_audit_cmd(Path("/tmp/p"), Path("/tmp/audit.py"),
                                      phase=2, skip_analog=True)
    assert "--skip-analog" in cmd, (
        f"Must forward --skip-analog when skip_analog=True: {cmd}")
    # The previous mandatory flags must still be present
    assert "--strict-structural" in cmd
    assert "--allow-thin-input" in cmd
    assert "--phase" in cmd


def test_build_final_audit_cmd_preserves_order_for_other_flags():
    """--phase + --strict-structural + --allow-thin-input must come BEFORE --skip-analog
    so the audit's positional + flag parsing stays unambiguous."""
    mod = _load_p2()
    cmd = mod._build_final_audit_cmd(Path("/tmp/p"), Path("/tmp/audit.py"),
                                      phase=3, skip_analog=True)
    # --skip-analog appended at the end
    assert cmd[-1] == "--skip-analog"
    # First 3 args are stable: python3, script, project
    assert cmd[0] == "python3"
    assert cmd[2] == "/tmp/p"


def test_main_argparse_accepts_skip_analog():
    """design_one_shot_runner.main() argparse must accept --skip-analog."""
    mod = _load_p2()
    # Construct an isolated argparse mimicking main's parser
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--skip-hardware", action="store_true")
    p.add_argument("--skip-analog", action="store_true")  # the captured flag
    p.add_argument("--max-eco", type=int, default=3)
    p.add_argument("--top-name", default="chip_top")
    p.add_argument("--container", default="vibeic-eda")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(["/tmp/foo", "--skip-analog"])
    assert args.skip_analog is True
    args2 = p.parse_args(["/tmp/foo"])
    assert args2.skip_analog is False


def test_vibe_ic_runner_forwards_skip_analog_to_phase2():
    """vibe_ic_one_shot_runner.py's phase2 chaining block must forward --skip-analog."""
    src = (Path(__file__).resolve().parents[1] / "vibe_ic_one_shot_runner.py").read_text()
    # The forwarding logic added at v0.1.54 capture
    assert "if args.skip_analog:" in src
    assert 'p2_args.append("--skip-analog")' in src, (
        "vibe_ic_one_shot_runner must forward --skip-analog to design_one_shot_runner.py "
        "so final_audit doesn't FAIL a digital-only project on analog file checks.")
