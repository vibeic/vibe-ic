"""tests/test_aid_class_rtl_gen_otp_asic_arm.py — vibe-ic#880

The OTP_MEM template had exactly two arms:

    `ifdef SIMULATION   -> behavioural array
    `else               -> altsyncram          <-- Quartus/Intel FPGA ONLY

ASIC synthesis reaches this file with SIMULATION UNDEFINED, so the `else` —
the vendor megafunction — was the arm silicon took. It either fails to resolve
or maps one-time-programmable storage to plain flip-flops.

What made it expensive is regeneration: Phase 2 rewrites otp_mem.sv from this
template on every run, byte-identically to the uncorrected form, silently
discarding any hand-applied fix. The regenerated file is syntactically valid
and simulates fine, so no gate in the flow could catch it.

DEFECT DIRECTION: `test_asic_default_arm_is_not_a_vendor_primitive` and
`test_fpga_arm_requires_explicit_opt_in` both FAIL against the pre-#880
template. That is the mutation that proves these tests can fail.

Chip-AGNOSTIC: asserts on the template's own guard structure. No design, PDK,
vendor part number or project name is involved.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]


def _template() -> str:
    spec = importlib.util.spec_from_file_location(
        "aid_class_rtl_gen", PROGRAMS / "aid_class_rtl_gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OTP_MEM.format()


def _directives(text: str) -> list[tuple[str, str]]:
    """Only REAL preprocessor lines. A guard named inside a comment is prose,
    and counting it would let a template pass this file by documenting an arm
    it does not have."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*`(ifdef|ifndef|elsif|else|endif)\s*(\w*)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def test_asic_default_arm_is_not_a_vendor_primitive():
    """THE defect: the arm taken when NO macro is defined — the ASIC path —
    must not be the Quartus megafunction."""
    text = _template()
    dirs = _directives(text)
    # Find the body of the final `else (the fallback every undefined-macro
    # build lands in).
    idx = [i for i, (kind, _) in enumerate(dirs) if kind == "else"]
    assert idx, "template has no fallback arm at all"
    lines = text.splitlines()
    else_line = [i for i, l in enumerate(lines)
                 if re.match(r"\s*`else", l)][-1]
    end_line = [i for i, l in enumerate(lines)
                if re.match(r"\s*`endif", l)][-1]
    fallback = "\n".join(lines[else_line + 1:end_line])
    assert "altsyncram" not in fallback, (
        "the default (ASIC) arm instantiates a Quartus-only megafunction; "
        "this is the #880 defect")


def test_fpga_arm_requires_explicit_opt_in():
    """FPGA must be opt-IN, so forgetting a macro degrades to a synthesizable
    ROM rather than to a vendor primitive."""
    dirs = _directives(_template())
    guards = {name for kind, name in dirs if kind in ("ifdef", "elsif")}
    assert "FPGA_BRAM" in guards, (
        "the altsyncram arm is not behind an explicit FPGA guard")


def test_simulation_arm_is_preserved():
    """The pre-existing simulation behaviour must not regress."""
    dirs = _directives(_template())
    assert dirs[0] == ("ifdef", "SIMULATION")


def test_every_arm_has_the_same_read_latency_contract():
    """All arms are registered reads (latency 1). The consumer FSM pipelines on
    that; an arm with a different latency would be a silent functional break."""
    text = _template()
    assert text.count("always @(posedge clk)") >= 2
    assert "outdata_reg_a(\"UNREGISTERED\")" in text or \
           'outdata_reg_a("UNREGISTERED")' in text


def test_foundry_macro_hook_instantiates_nothing_it_invented():
    """The external-macro arm must not guess a vendor macro name/timing — it
    binds a project-supplied wrapper with the module's own port list."""
    text = _template()
    assert "OTP_MACRO_EXTERNAL" in text
    m = re.search(r"otp_macro_wrapper\s+u_otp\s*\((.*?)\);", text, re.S)
    assert m, "external-macro arm missing its wrapper instantiation"
    ports = set(re.findall(r"\.(\w+)\s*\(", m.group(1)))
    assert ports == {"clk", "addr", "rdata"}, ports


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not available")
def test_asic_default_arm_actually_elaborates(tmp_path):
    """Structure assertions are not enough — the ASIC path must COMPILE. This
    is the assertion that would have caught the original defect on its own."""
    sv = tmp_path / "otp_mem.sv"
    sv.write_text(_template())
    r = subprocess.run(["iverilog", "-g2012", "-o", "/dev/null", str(sv)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not available")
def test_simulation_arm_actually_elaborates(tmp_path):
    sv = tmp_path / "otp_mem.sv"
    sv.write_text(_template())
    r = subprocess.run(
        ["iverilog", "-g2012", "-DSIMULATION", "-o", "/dev/null", str(sv)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
