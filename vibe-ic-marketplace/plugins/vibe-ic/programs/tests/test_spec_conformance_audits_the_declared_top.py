"""spec_conformance_check must audit the module the SPEC DECLARES, and must not
hard-fail a pin the INPUT marks optional.

Both anchored to one measured run (subservient / gf180mcuD, plugin 1.12.58, the
flow's own clause `spec_conformance_check --rtl-dir phase2/stage1/rtl --spec
phase1/generated_docs/L9_INTEGRATION_SPEC.json`):

  • L9_INTEGRATION_SPEC.json names its top under `top_module`, but the JSON spec
    loader read only `module`. `top = args.top or spec.module` therefore fell
    back to "the first module found" in --rtl-dir — the alphabetically-first
    SUBMODULE (bitserial_alu, 11 ports) instead of the declared top
    (subservient, 8 ports). 11 of the run's 16 ERRORs were port-extra findings
    naming that submodule's internal signals.

  • L9 marks `i_gpio` with `optional: true` (the input document offers the pin
    rather than requiring it). l9_rtl_pin_consistency_check honours that flag
    and reports it advisory; this gate ignored it and emitted a blocking
    port-missing ERROR, so two gates returned contradictory verdicts from the
    identical L9 field.

Each test carries its own negative control so neither fix can be satisfied by
code that simply stops reporting things.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_conformance_check.py'
assert SCRIPT.exists()

# Two modules; the SUBMODULE sorts first, exactly as in the measured run.
RTL_ALU = """
module aaa_submodule(input i_clk, input i_start, input [31:0] i_a,
                     output [31:0] o_result, output o_done);
  assign o_result = i_a; assign o_done = i_start & i_clk;
endmodule
"""
RTL_TOP = """
module zz_top(input i_clk, input i_rst, output o_gpio);
  assign o_gpio = i_clk & ~i_rst;
endmodule
"""

TOP_SPEC_PORTS = [
    {"name": "i_clk", "direction": "input", "width": 1},
    {"name": "i_rst", "direction": "input", "width": 1},
    {"name": "o_gpio", "direction": "output", "width": 1},
]


def run(tmp_path, spec_obj, *extra):
    rtl_dir = tmp_path / 'rtl'
    rtl_dir.mkdir(exist_ok=True)
    (rtl_dir / 'aaa_submodule.v').write_text(RTL_ALU)
    (rtl_dir / 'zz_top.v').write_text(RTL_TOP)
    spec = tmp_path / 'L9_INTEGRATION_SPEC.json'
    spec.write_text(json.dumps(spec_obj))
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--rtl-dir', str(rtl_dir),
         '--spec', str(spec), '--json', str(jf), *extra],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


def rules(findings):
    return {f['rule'] for f in findings}


# --------------------------------------------------------------- top selection
def test_a_json_spec_naming_its_top_under_top_module_is_audited_against_that_top(tmp_path):
    """The declared top conforms, so the gate must be GREEN — not a pile of
    port-extra findings about a submodule the spec never described."""
    res, findings = run(tmp_path, {"top_module": "zz_top", "ports": TOP_SPEC_PORTS})
    assert res.returncode == 0, res.stdout + res.stderr
    assert 'port-extra' not in rules(findings)
    assert 'port-missing' not in rules(findings)


def test_CONTROL_the_module_key_still_selects_the_top(tmp_path):
    """The pre-existing `module` key must keep working byte-for-byte: this fix
    ADDS an accepted spelling, it does not move the existing one."""
    res, findings = run(tmp_path, {"module": "zz_top", "ports": TOP_SPEC_PORTS})
    assert res.returncode == 0, res.stdout + res.stderr
    assert 'port-extra' not in rules(findings)


def test_CONTROL_a_declared_top_that_really_does_mismatch_still_FAILS(tmp_path):
    """Negative control for the selection fix: selecting the right module must
    not be a way of finding nothing. A genuine mismatch on the DECLARED top
    still blocks with the exact code."""
    res, findings = run(tmp_path, {
        "top_module": "zz_top",
        "ports": TOP_SPEC_PORTS + [
            {"name": "o_required_pin", "direction": "output", "width": 1}],
    })
    assert res.returncode == 1, res.stdout + res.stderr
    assert 'port-missing' in rules(findings)


# ------------------------------------------------------------ optional pins
def test_an_optional_spec_pin_absent_from_the_rtl_is_INFO_not_a_blocking_error(tmp_path):
    res, findings = run(tmp_path, {
        "top_module": "zz_top",
        "ports": TOP_SPEC_PORTS + [
            {"name": "i_gpio", "direction": "input", "width": 1, "optional": True}],
    })
    assert res.returncode == 0, res.stdout + res.stderr
    assert 'port-missing' not in rules(findings)
    assert 'port-optional-not-implemented' in rules(findings)
    sev = {f['rule']: f['severity'] for f in findings}
    assert sev['port-optional-not-implemented'] == 'INFO'


def test_CONTROL_a_pin_NOT_marked_optional_is_still_a_blocking_error(tmp_path):
    """The same pin, same position, `optional` absent — must still block. Without
    this, the optional fix would be satisfied by code that downgrades every
    missing port."""
    res, findings = run(tmp_path, {
        "top_module": "zz_top",
        "ports": TOP_SPEC_PORTS + [
            {"name": "i_gpio", "direction": "input", "width": 1}],
    })
    assert res.returncode == 1, res.stdout + res.stderr
    assert 'port-missing' in rules(findings)


def test_CONTROL_optional_false_is_treated_as_required(tmp_path):
    """An explicit `optional: false` must not be read as truthy."""
    res, findings = run(tmp_path, {
        "top_module": "zz_top",
        "ports": TOP_SPEC_PORTS + [
            {"name": "i_gpio", "direction": "input", "width": 1, "optional": False}],
    })
    assert res.returncode == 1, res.stdout + res.stderr
    assert 'port-missing' in rules(findings)
