"""Tool front ends own generic P0 shape; design-intent gates remain separate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as flow  # noqa: E402
import flow_step_output_content_check as content  # noqa: E402
import p0_tool_frontend_check as frontend  # noqa: E402
import ic_class_profile as classes  # noqa: E402


#: THE RETIREMENT RECORD for the P0 regex gates this front end replaced
#: (1a27f263d). It lives in this TEST file on purpose: `gate_is_wired_check`
#: credits a gate name written as a table literal in a program that can spawn
#: as a dispatch, so the same record in `p0_tool_frontend_check.py` would read
#: as the retired gate's caller. `tests/` is not a wiring source.
#:
#: Each row names the Verilator code that now blocks the retired gate's only
#: ERROR-severity finding, and a line of REAL tool output carrying it
#: (vibeic-eda 0.3.79, sha256:93d88e9e…, Verilator 5.053) on the retired
#: gate's own known-bad shape. MEASURED on that image with `check()`, over the
#: retired checker's own test fixtures: 4 known-bad bit-selects refused as
#: SELRANGE, 4 known-good passed, and a parameter-width select the regex could
#: not see (`reg [W-1:0] idx` indexed `[6:0]`, W=5) refused too.
#:
#: `program`: `deleted` is the retirement of a gate file, because
#: `gate_is_wired_check` counts every `programs/*_check|_audit.py` stem and a
#: retired gate left there reads as a gate nothing invokes. `library` means
#: other programs still import the file for its parser, which keeps it wired.
RETIRED_REGEX_GATES = {
    "bitwidth_consistency_check": {
        "blocking_code": "SELRANGE",
        "retired_finding": "bitselect-out-of-range: a [hi:lo] select outside "
                           "the signal's declared range",
        "tool_line": "%Warning-SELRANGE: top.v:7:40: Selection index out of "
                     "range: 6:0 outside 4:0",
        "program": "deleted",
    },
    "module_port_audit": {
        "blocking_code": "PINNOTFOUND",
        "retired_finding": "MISMATCH: a named connection to a port the "
                           "instantiated module does not declare (its "
                           "WIDTH_MISMATCH and UNCONNECTED were WARN, and stay "
                           "visible as WIDTH*/PINMISSING diagnostics)",
        "tool_line": "%Error-PINNOTFOUND: top.v:7:25: Pin not found: "
                     "'sys_clk_5m'",
        "program": "library",
    },
}


def _project(tmp_path):
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.sv").write_text("module top(input logic a); endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "top"}))
    return tmp_path


def test_tool_codes_replace_only_covered_regex_gates(monkeypatch, tmp_path):
    project = _project(tmp_path)
    calls = []

    def fake(tool, args, root, image):
        calls.append((tool, args))
        if tool == "verilator":
            return subprocess.CompletedProcess([], 0, "", "%Warning-SELRANGE: top.sv:1:1: out of range\n")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(frontend, "_invoke", fake)
    result = frontend.check(project, "test-image")
    assert not result["passed"]
    assert "Verilator Warning-SELRANGE" in result["findings"]
    assert [name for name, _ in calls] == ["yosys", "verilator"]
    assert "hierarchy -check -top top" in calls[0][1][-1]
    assert "p0_tool_frontend_check" not in flow._STRUCTURAL_RTL_GATES
    assert "bitwidth_consistency_check" not in flow._STRUCTURAL_RTL_GATES
    assert "module_port_audit" not in flow._STRUCTURAL_RTL_GATES
    # Current released Verilator accepts this SV extension without a code.
    assert "function_void_with_output_check" in flow._STRUCTURAL_RTL_GATES


def test_no_frontend_execution_cannot_pass(monkeypatch, tmp_path):
    project = _project(tmp_path)
    monkeypatch.setattr(frontend, "_invoke", lambda *args: (_ for _ in ()).throw(FileNotFoundError("missing")))
    result = frontend.check(project, "test-image")
    assert not result["passed"]
    assert "unavailable" in result["findings"][0]


def test_unconnected_and_width_warnings_remain_visible_without_new_block(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def fake(tool, args, root, image):
        text = ("%Warning-PINMISSING: top.sv:1:1: missing pin\n"
                "%Warning-WIDTHEXPAND: top.sv:1:1: width mismatch\n") if tool == "verilator" else ""
        return subprocess.CompletedProcess([], 0, "", text)

    monkeypatch.setattr(frontend, "_invoke", fake)
    result = frontend.check(project, "test-image")
    assert result["passed"]
    assert [row["code"] for row in result["tools"]["Verilator.Lint"]["diagnostics"]] == [
        "PINMISSING", "WIDTHEXPAND"]


def test_rtl_content_delegates_parser_and_retains_source_presence(monkeypatch, tmp_path):
    project = _project(tmp_path)
    rtl = project / "phase2/stage1/rtl/top.sv"
    rtl.write_text("module top; // endmodule appears only in a comment\n")
    calls = []
    monkeypatch.setattr(frontend, "check", lambda *args: (calls.append(args) or
                                                    {"passed": True, "findings": []}))
    assert content.check(project, "rtl") == []
    assert calls
    rtl.write_text("")
    assert content.check(project, "rtl")


def test_bus_intent_uses_the_declared_class(monkeypatch, tmp_path):
    monkeypatch.setattr(classes, "detect_ic_class", lambda project: {"ic_class": "test_class"})
    monkeypatch.setattr(classes, "class_verification_flags", lambda name: {
        "registry_matched": True, "half_duplex_bus": False,
        "command_protocol_applicable": True, "analog_applicable": True,
        "verification_track": "generic_full_stack"})
    skipped = flow._class_skipped_gates(tmp_path)
    assert "self_rx_mask_check" in skipped
    assert "half_duplex_bus=false" in skipped["self_rx_mask_check"]
    assert "crc_completeness_check" not in skipped
    monkeypatch.setattr(classes, "class_verification_flags", lambda name: {
        "registry_matched": True, "half_duplex_bus": True,
        "command_protocol_applicable": True, "analog_applicable": True,
        "verification_track": "aid_protocol"})
    assert "self_rx_mask_check" not in flow._class_skipped_gates(tmp_path)


def test_command_intent_needs_class_and_l3_l4_declarations(monkeypatch, tmp_path):
    monkeypatch.setattr(classes, "detect_ic_class", lambda project: {"ic_class": "test_class"})
    monkeypatch.setattr(classes, "class_verification_flags", lambda name: {
        "registry_matched": True, "half_duplex_bus": True,
        "command_protocol_applicable": False, "analog_applicable": True,
        "verification_track": "generic_full_stack"})
    assert "cmd_arg_range_validation_check" not in flow._class_skipped_gates(tmp_path)
    monkeypatch.setattr(flow, "_ldocs_record_no_opcodes", lambda project: True)
    assert "cmd_arg_range_validation_check" in flow._class_skipped_gates(tmp_path)


@pytest.mark.parametrize("gate", sorted(RETIRED_REGEX_GATES))
def test_a_retired_gate_is_replaced_by_a_blocking_tool_code(gate, monkeypatch, tmp_path):
    """The retirement is true only while the replacement still refuses the
    retired gate's finding: the code blocks, the real tool line carrying it
    fails `check()`, and the clause that runs `check()` is still in P0."""
    rec = RETIRED_REGEX_GATES[gate]
    assert rec["blocking_code"] in frontend.BLOCKING_CODES, gate
    project = _project(tmp_path)

    def fake(tool, args, root, image):
        text = rec["tool_line"] + "\n" if tool == "verilator" else ""
        return subprocess.CompletedProcess([], 0, "", text)

    monkeypatch.setattr(frontend, "_invoke", fake)
    result = frontend.check(project, "test-image")
    assert not result["passed"], gate
    assert any(f.endswith("-" + rec["blocking_code"]) for f in result["findings"])
    flow_yaml = (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert 'program_exit_zero: "flow_step_output_content_check . --mode rtl"' in flow_yaml


@pytest.mark.parametrize("gate", sorted(RETIRED_REGEX_GATES))
def test_a_retired_gate_leaves_the_umbrella_and_its_registers(gate):
    """Out of the P0 umbrella, and so out of the register of gates the
    umbrella carries but cannot drive (vibe-ic#559)."""
    assert gate not in flow._STRUCTURAL_RTL_GATES
    assert gate not in flow._UNDRIVABLE_BY_STRUCTURAL_UMBRELLA


@pytest.mark.parametrize("gate", sorted(RETIRED_REGEX_GATES))
def test_a_retired_gate_file_is_deleted_or_still_a_library(gate):
    """A deleted gate cannot sit in `gate_is_wired_check`'s population as a
    gate nothing invokes; a library one must still exist for its importers."""
    path = PROGRAMS / f"{gate}.py"
    program = RETIRED_REGEX_GATES[gate]["program"]
    assert program in ("deleted", "library"), program
    assert path.exists() is (program == "library"), path


# ── audit §3.16 / R-0929-TOOL-DEFAULT wave 1: LATCH blocks at P0 ────────────

#: REAL Verilator 5.053 output (vibeic-eda 0.3.86) on a combinational
#: `always @(*) if (en) q = d;` -- the if-form the regex latch rule missed.
LATCH_LINE = ("%Warning-LATCH: top.v:2:3: Latch inferred for signal 'q' (not "
              "all control paths of combinational always assign a value)\n")


def test_an_inferred_latch_blocks_the_front_end(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def fake(tool, args, root, image):
        text = LATCH_LINE if tool == "verilator" else ""
        return subprocess.CompletedProcess([], 0, "", text)

    monkeypatch.setattr(frontend, "_invoke", fake)
    result = frontend.check(project, "test-image")
    assert not result["passed"]
    assert "Verilator Warning-LATCH" in result["findings"]


def test_p0_and_step2_block_one_code_list():
    """Every code P0 blocks is also blocked by step 2's Verilator.Lint judge,
    so the two front ends cannot disagree about a class they both see."""
    import verilator_lint_gate as step2
    assert "LATCH" in frontend.BLOCKING_CODES
    assert frontend.BLOCKING_CODES <= step2.BLOCKING_WARNINGS


# ── audit §3.16 P0: the Yosys elaboration is KEPT, not written to /dev/null ──

def _elab_fake(rc=0, doc=None):
    """Yosys's file write, faked: write the JSON where the script says."""
    import re as _re

    def fake(tool, args, root, image):
        if tool == "yosys":
            m = _re.search(r"write_json (\S+)", args[-1])
            assert m and m.group(1) != "/dev/null", args[-1]
            if rc == 0:
                Path(m.group(1)).write_text(json.dumps(doc if doc is not None else {
                    "modules": {"top": {"attributes": {"top": "00000001"},
                                        "ports": {"a": {"direction": "input",
                                                        "bits": [2]}}}}}))
            return subprocess.CompletedProcess([], rc, "", "")
        return subprocess.CompletedProcess([], 0, "", "")
    return fake


def test_p0_keeps_the_tool_elaboration(monkeypatch, tmp_path):
    project = _project(tmp_path)
    monkeypatch.setattr(frontend, "_invoke", _elab_fake())
    result = frontend.check(project, "test-image")
    kept = project / frontend.RTL_ELAB_REL
    assert result["passed"] and kept.is_file()
    assert json.loads(kept.read_text())["modules"]["top"]["ports"]["a"]["direction"] == "input"
    assert result["elaboration"]["written"] is True
    assert result["elaboration"]["top"] == "top"
    yosys_argv = result["tools"]["Yosys.JsonHeader"]["argv"]
    assert yosys_argv[:4] == ["yosys", "-Q", "-T", "-p"]
    assert "read_slang --single-unit" in yosys_argv[4]
    assert "read_verilog" not in yosys_argv[4]
    assert result["tools"]["Verilator.Lint"]["argv"][:2] == ["verilator", "--lint-only"]


def test_a_failed_or_empty_elaboration_keeps_nothing_and_clears_the_last(
        monkeypatch, tmp_path):
    project = _project(tmp_path)
    kept = project / frontend.RTL_ELAB_REL
    kept.parent.mkdir(parents=True)
    kept.write_text('{"modules": {"stale": {}}}')
    monkeypatch.setattr(frontend, "_invoke", _elab_fake(rc=1))
    result = frontend.check(project, "test-image")
    assert not kept.exists() and result["elaboration"]["written"] is False
    assert "Yosys elaboration failed" in result["findings"]
    monkeypatch.setattr(frontend, "_invoke", _elab_fake(doc={"modules": {}}))
    result = frontend.check(project, "test-image")
    assert not kept.exists() and "no module" in result["elaboration"]["why"]


def test_the_docker_path_mounts_only_the_elaboration_scratch_writable(
        monkeypatch, tmp_path):
    """The project stays read-only; the one rw mount is P0's own scratch."""
    import _watchdog
    project = _project(tmp_path)
    seen = {}
    monkeypatch.setattr(frontend.shutil, "which",
                        lambda t: "/usr/bin/docker" if t == "docker" else None)

    def run(command, **kw):
        seen["cmd"] = command
        raise RuntimeError("stop after composing the command")
    monkeypatch.setattr(_watchdog, "run_host_supervised", run)
    scratch = tmp_path / (frontend._ELAB_SCRATCH_PREFIX + "x")
    scratch.mkdir()
    with pytest.raises(RuntimeError):
        frontend._invoke("yosys", ["-p", f"proc; write_json {scratch}/rtl_elab.json"],
                         project, "img")
    cmd = seen["cmd"]
    vols = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    root = str(project.resolve())
    assert f"{root}:{root}:ro" in vols
    assert f"{scratch}:{scratch}" in vols
    assert len(vols) == 2


def test_isolated_elaboration_output_preserves_prior_project_evidence(tmp_path, monkeypatch):
    project = _project(tmp_path)
    prior = project / frontend.RTL_ELAB_REL
    prior.parent.mkdir(parents=True, exist_ok=True)
    prior.write_bytes(b'prior-evidence\n')
    output = tmp_path / 'isolated-output'
    monkeypatch.setattr(frontend, '_invoke', _elab_fake())
    result = frontend.check(project, 'test-image', output_project=output)
    assert result['passed'] is True
    assert prior.read_bytes() == b'prior-evidence\n'
    assert (output / frontend.RTL_ELAB_REL).is_file()
    assert result['elaboration']['written'] is True
