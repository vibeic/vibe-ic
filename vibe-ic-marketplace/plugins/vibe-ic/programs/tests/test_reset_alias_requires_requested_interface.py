"""Automatic interface adaptation needs a requested contract, not a guessed TB.

Neutral runtime controls cover both refusal and intentional compatibility.
The checked-in reference-IP control derives a spelling variant in a temporary
project; no benchmark inputs, expected outputs, or external harness are read.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "programs"))
import design_one_shot_runner as R  # noqa: E402
import reset_clock_variant_alias as V  # noqa: E402


def _stage(project, source="reset_n"):
    path = project / "phase2/stage1/rtl/dut.sv"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"module dut(input {source}, input d, output q);\n"
        f"assign q = {source} & d;\nendmodule\n")
    return path


def _prompt(project, text):
    path = project / "input/phase1_prompt.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _contract(project, names, top="dut"):
    path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"top_module": top, "top_ports": names}))


def _ports(path, top="dut"):
    return {p[2] for p in V.parse_module_ports(path.read_text(), top)}


@pytest.mark.parametrize("source", ["reset_n", "reset", "clock"])
@pytest.mark.parametrize("top", ["dut", "chip_top"])
def test_no_contract_keeps_original_bytes(tmp_path, source, top):
    path = _stage(tmp_path, source)
    before = path.read_bytes()
    result = R.step_reset_clock_variant_aliases(tmp_path, top)
    assert path.read_bytes() == before
    assert result.status == "SKIP"
    assert "request" in result.detail.lower()


@pytest.mark.parametrize("source", ["reset_n", "reset", "clock"])
def test_native_prompt_never_adds_speculative_port(tmp_path, source):
    path = _stage(tmp_path, source)
    _prompt(tmp_path, f"Public input port `{source}` drives the operation.\n")
    before = path.read_bytes()
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert _ports(path) == {source, "d", "q"}
    assert path.read_bytes() == before
    assert result.status == "SKIP"


@pytest.mark.parametrize("structured", [False, True])
def test_two_named_resets_do_not_authorize_combining_them(tmp_path, structured):
    path = _stage(tmp_path)
    if structured:
        _contract(tmp_path, ["reset_n", "rst_n", "d", "q"])
    else:
        _prompt(tmp_path, "The input ports are `reset_n` and `rst_n`.\n")
    before = path.read_bytes()
    R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert path.read_bytes() == before
    assert _ports(path) == {"reset_n", "d", "q"}


@pytest.mark.parametrize("text", [
    "The implementation may internally call reset `rst_n`.\n",
    "Input ports:\nrst_n: active-low reset\n",
])
def test_prose_or_incomplete_contract_is_not_rename_authority(tmp_path, text):
    path = _stage(tmp_path)
    _prompt(tmp_path, text)
    before = path.read_bytes()
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert path.read_bytes() == before
    assert result.status == "SKIP"


def test_malformed_contract_refuses_mutation(tmp_path):
    path = _stage(tmp_path)
    _contract(tmp_path, ["rst_n", "d", "q"])
    (tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text("{")
    before = path.read_bytes()
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert path.read_bytes() == before
    assert result.status == "SKIP"
    assert "request" in result.detail.lower()


@pytest.mark.parametrize("source,target", [
    ("reset_n", "rst_n"), ("reset", "rst"), ("clock", "clk"),
])
def test_explicit_requested_variant_remains_supported(tmp_path, source, target):
    path = _stage(tmp_path, source)
    _contract(tmp_path, [target, "d", "q"])
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert result.status == "PASS", result.detail
    assert _ports(path) == {target, "d", "q"}
    assert R.step_reset_clock_variant_aliases(tmp_path, "dut").status == "SKIP"


def test_complete_public_sections_can_request_variant(tmp_path):
    path = _stage(tmp_path)
    _prompt(tmp_path, "Input ports:\nrst_n: active-low reset\nd: data\n\n"
            "Output ports:\nq: output\n")
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert result.status == "PASS", result.detail
    assert _ports(path) == {"rst_n", "d", "q"}


def test_opposite_polarity_contract_cannot_request_variant(tmp_path):
    path = _stage(tmp_path)
    _contract(tmp_path, ["rst", "d", "q"])
    before = path.read_bytes()
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert path.read_bytes() == before
    assert result.status == "SKIP"


def _elaborate(tmp_path, path, tb):
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog unavailable: runtime elaboration not measured")
    tb_path = tmp_path / "tb.sv"
    tb_path.write_text(tb)
    output = tmp_path / "simulation"
    result = subprocess.run([iv, "-g2012", "-s", "tb", "-o", str(output),
                             str(path), str(tb_path)],
                            capture_output=True, text=True, timeout=20)
    return result, output


def test_native_wildcard_connection_elaborates_before_and_after_step(tmp_path):
    path = _stage(tmp_path)
    _prompt(tmp_path, "Input port `reset_n` is active low.\n")
    tb = "module tb; reg reset_n=1,d=1; wire q; dut u(.*); endmodule\n"
    before, _ = _elaborate(tmp_path, path, tb)
    assert before.returncode == 0, before.stderr
    R.step_reset_clock_variant_aliases(tmp_path, "dut")
    after, _ = _elaborate(tmp_path, path, tb)
    assert after.returncode == 0, after.stderr


def test_explicit_additive_emitter_retains_intentional_compatibility(tmp_path):
    path = _stage(tmp_path)
    core = path.read_text().replace("module dut(", "module core(")
    wrapper = V.emit_variant_alias_wrapper(
        "core", V.parse_module_ports(core, "core"), {}, wrapper_name="dut",
        additive_reset_map={"reset_n": "rst_n"})
    path.write_text(core + wrapper)
    tb = """module tb;
reg reset_n=1, rst_n=1, d=1;
wire q;
dut u(.*);
initial begin
  #1; if(q !== 1) $fatal(1, "released resets");
  reset_n=0; #1; if(q !== 0) $fatal(1, "native reset");
  reset_n=1; rst_n=0; #1; if(q !== 0) $fatal(1, "requested alias reset");
  rst_n=1; #1; if(q !== 1) $fatal(1, "both released");
  $display("INTENTIONAL_COMPATIBILITY_PASS"); $finish;
end
endmodule
"""
    compiled, output = _elaborate(tmp_path, path, tb)
    assert compiled.returncode == 0, compiled.stderr
    simulator = shutil.which("vvp")
    if not simulator:
        pytest.skip("vvp unavailable: intentional compatibility not simulated")
    result = subprocess.run([simulator, str(output)], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INTENTIONAL_COMPATIBILITY_PASS" in result.stdout


@pytest.mark.parametrize("requested", [False, True])
def test_checked_in_reference_ip_variant_obeys_contract(tmp_path, requested):
    reference = require_repo("vibe-ic-marketplace", "reference-plugins",
                             "example-ip", "files", "tiny_uart.v")
    original = reference.read_text()
    top = re.search(r"\bmodule\s+(\w+)", original).group(1)
    path = tmp_path / "phase2/stage1/rtl/reference.sv"
    path.parent.mkdir(parents=True)
    # Derive an equivalent native spelling from a real checked-in artifact.
    # It is not a hand-authored substitute for the reference module's body.
    native = re.sub(r"\brst_n\b", "reset_n", original)
    path.write_text(native)
    if requested:
        _contract(tmp_path, [p[2] for p in V.parse_module_ports(original, top)], top)
    result = R.step_reset_clock_variant_aliases(tmp_path, top)
    if requested:
        assert result.status == "PASS", result.detail
        assert _ports(path, top) == {p[2] for p in V.parse_module_ports(original, top)}
    else:
        assert path.read_text() == native
        assert result.status == "SKIP"


@pytest.mark.parametrize("flat", ["0", "1"])
def test_flat_mode_is_not_interface_authority(tmp_path, monkeypatch, flat):
    path = _stage(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv("VIBE_IC_RCVAR_WHITEBOX_FLAT", flat)
    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert path.read_bytes() == before
    assert result.status == "SKIP"


def _cli(tmp_path, aliases):
    path = _stage(tmp_path)
    output = tmp_path / "wrapper.sv"
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "programs/reset_clock_variant_alias.py"),
         "--rtl", str(path), "--module", "dut", "--out", str(output), *aliases],
        capture_output=True, text=True, timeout=20)
    return path, output, result


def test_cli_without_explicit_mapping_does_not_guess(tmp_path):
    path, output, result = _cli(tmp_path, [])
    assert result.returncode == 2
    assert not output.exists()
    assert "alias" in result.stderr
    assert _ports(path) == {"reset_n", "d", "q"}


def test_cli_explicit_mapping_remains_supported(tmp_path):
    path, output, result = _cli(tmp_path, ["--alias", "reset_n=nrst"])
    assert result.returncode == 0, result.stderr
    assert _ports(output, "dut_aliased") == {"nrst", "d", "q"}
    assert _ports(path) == {"reset_n", "d", "q"}


@pytest.mark.parametrize("aliases", [
    ["--alias", "reset_n=rst"],
    ["--alias", "arst_n=rst_n"],
    ["--alias", "reset_n"],
    ["--alias", "reset_n=rst_n", "--alias", "reset_n=nrst"],
])
def test_cli_rejects_invalid_explicit_mapping(tmp_path, aliases):
    path, output, result = _cli(tmp_path, aliases)
    assert result.returncode == 2
    assert not output.exists()
    assert "error:" in result.stderr
    assert _ports(path) == {"reset_n", "d", "q"}
