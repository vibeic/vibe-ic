"""Reverse tests for the Step-14 native producer authority boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yosys_tiecell_recipe_order_check as tie


_CLEAN = (
    "read_verilog -sv a.v; synth -top t -flatten; "
    "dfflibmap -liberty /p/lib.lib; abc -liberty /p/lib.lib; "
    "setundef -zero; hilomap -hicell HI Y -locell LO Y; splitnets; "
    "clean; write_verilog out.v"
)

_REAL_LIBRELANE_COMMAND = (
    "yosys -y /usr/local/lib/python3.12/dist-packages/librelane/scripts/pyosys/"
    "synthesize.py -- --config-in __FOLDER__/config.json "
    "--extra-in __FOLDER__/extra.json --output __FOLDER__/top.nl.v"
)

_NATIVE_LOG_CLEAN = """
Yosys 0.69+ (git sha1 d12c0b31a, Release)
196. Executing DFFLIBMAP pass (mapping DFF/DLATCH cells to sequential cells).
197. Executing ABC pass (technology mapping using ABC).
198. Executing SETUNDEF pass (replace undef values with defined constants).
199. Executing HILOMAP pass (mapping to constant drivers).
200. Executing SPLITNETS pass (splitting up multi-bit signals).
201. Executing INSBUF pass (insert buffer cells for connected wires).
"""

_NATIVE_LOG_DIRTY = """
Yosys 0.69+ (git sha1 d12c0b31a, Release)
196. Executing DFFLIBMAP pass (mapping DFF/DLATCH cells to sequential cells).
197. Executing ABC pass (technology mapping using ABC).
198. Executing HILOMAP pass (mapping to constant drivers).
199. Executing SETUNDEF pass (replace undef values with defined constants).
200. Executing SPLITNETS pass (splitting up multi-bit signals).
201. Executing OPT_CLEAN pass (remove unused cells and wires).
"""


def _receipt(project: Path, name: str, commands: str, *, bind_commands: bool,
             step: str = "Yosys.Synthesis") -> Path:
    folder = project / "phase3" / "librelane" / name
    folder.mkdir(parents=True)
    command_path = folder / "COMMANDS"
    command_path.write_text(commands)
    marker = folder / "marker"
    marker.write_text("retained\n")
    hashes = {"marker": hashlib.sha256(marker.read_bytes()).hexdigest()}
    if bind_commands:
        hashes["COMMANDS"] = hashlib.sha256(command_path.read_bytes()).hexdigest()
    receipt = folder / "vibeic_receipt.json"
    receipt.write_text(json.dumps({"input": {"step": step}, "sha256": hashes}))
    return folder


def _wrapper_receipt(project: Path, log: str, *, command: str = _REAL_LIBRELANE_COMMAND,
                     bind_commands: bool = True) -> Path:
    folder = project / "phase3" / "librelane" / "02-yosys-synthesis"
    folder.mkdir(parents=True)
    command = command.replace("__FOLDER__", str(folder))
    command_path = folder / "COMMANDS"
    command_path.write_text(command + "\n")
    log_path = folder / "invocation.log"
    log_path.write_text(log)
    config = folder / "config.json"
    config.write_text(json.dumps({"meta": {"step": "Yosys.Synthesis"},
                                  "SYNTH_TIE_UNDEFINED": "low"}))
    extra = folder / "extra.json"
    extra.write_text("{}\n")
    marker = folder / "state_out.json"
    marker.write_text("{}\n")
    hashes = {
        "state_out.json": hashlib.sha256(marker.read_bytes()).hexdigest(),
        "invocation.log": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "config.json": hashlib.sha256(config.read_bytes()).hexdigest(),
        "extra.json": hashlib.sha256(extra.read_bytes()).hexdigest(),
    }
    if bind_commands:
        hashes["COMMANDS"] = hashlib.sha256(command_path.read_bytes()).hexdigest()
    (folder / "vibeic_receipt.json").write_text(json.dumps({
        "input": {"step": "Yosys.Synthesis"}, "sha256": hashes}))
    return folder


def test_old_native_receipt_without_commands_digest_is_not_checked(tmp_path):
    """A mutable adjacent COMMANDS file cannot certify a native recipe."""
    _receipt(tmp_path, "02-yosys-synthesis", "yosys -p %r" % _CLEAN,
             bind_commands=False)
    legacy = tmp_path / "phase3" / "synth" / "legacy.ys"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_CLEAN)
    report = tie.audit_project(tmp_path)
    assert report["mode"] == "native_pyosys"
    assert report["verdict"] == "NOT_CHECKED", report
    assert not any(f.get("verdict") == "CLEAN" for f in report["findings"])


def test_non_yosys_p_option_is_not_a_native_recipe(tmp_path):
    _receipt(tmp_path, "02-yosys-synthesis", "printf -p %r" % _CLEAN,
             bind_commands=True)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report
    assert all(f.get("verdict") != "CLEAN" for f in report["findings"])


def test_native_config_without_receipt_does_not_fall_back_to_legacy(tmp_path):
    folder = tmp_path / "phase3" / "librelane" / "02-yosys-synthesis"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(
        json.dumps({"meta": {"step": "Yosys.Synthesis"}}))
    legacy = tmp_path / "phase3" / "synth" / "legacy.ys"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_CLEAN)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report
    assert report["findings"][0]["verdict"] == "NOT_CHECKED"


def test_clean_native_candidate_plus_incomplete_candidate_is_not_clean(tmp_path):
    _receipt(tmp_path, "01-yosys-synthesis", "yosys -p %r" % _CLEAN,
             bind_commands=True)
    _receipt(tmp_path, "02-yosys-synthesis", "yosys -p %r" % _CLEAN,
             bind_commands=False)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report
    assert report["summary"]["judged"] >= 1, report


def test_real_librelane_wrapper_is_judged_from_executed_log(tmp_path):
    _wrapper_receipt(tmp_path, _NATIVE_LOG_DIRTY)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "VIOLATION", report
    rules = {row["rule"] for row in report["violations"]}
    assert rules == {"RULE1_setundef_zero_before_hilomap",
                     "RULE2_no_opt_clean_after_hilomap"}
    assert "COMMANDS + phase3/librelane/02-yosys-synthesis/invocation.log" \
        in report["findings"][0]["source"]


def test_real_librelane_wrapper_clean_log_is_measured(tmp_path):
    _wrapper_receipt(tmp_path, _NATIVE_LOG_CLEAN)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "CLEAN", report
    assert report["summary"] == {"skipped": False, "reason": "native_pyosys_receipt",
                                  "judged": 1, "denominator": 1}


def test_real_librelane_wrapper_requires_bound_commands_and_log(tmp_path):
    _wrapper_receipt(tmp_path, _NATIVE_LOG_CLEAN, bind_commands=False)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report
    assert "COMMANDS digest" in report["findings"][0]["reason"]


def test_real_librelane_wrapper_rejects_mutated_execution_log(tmp_path):
    folder = _wrapper_receipt(tmp_path, _NATIVE_LOG_CLEAN)
    (folder / "invocation.log").write_text(_NATIVE_LOG_DIRTY)
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report
    assert "invocation.log" in report["findings"][0]["reason"]


def test_real_librelane_wrapper_rejects_shell_wrapper(tmp_path):
    _wrapper_receipt(tmp_path, _NATIVE_LOG_CLEAN,
                     command="sh -c 'yosys -y /usr/local/lib/python3.12/dist-packages/"
                             "librelane/scripts/pyosys/synthesize.py -- --config-in x "
                             "--extra-in y --output z'")
    report = tie.audit_project(tmp_path)
    assert report["verdict"] == "NOT_CHECKED", report


def test_zero_byte_source_changes_step15_input_identity(tmp_path):
    from programs import flow_declared_producer_run as producer

    source = tmp_path / "phase2" / "stage2" / "constraints" / "in.sdc"
    source.parent.mkdir(parents=True)
    source.write_text("create_clock -period 10 [get_ports clk]\n")
    clauses = [{"target": "reports/step15.json", "program": "x",
                "step": "15", "command": "x", "siblings": []}]
    before = producer._current_input_identity(tmp_path, clauses)
    source.write_text("")
    after = producer._current_input_identity(tmp_path, clauses)
    assert "phase2/stage2/constraints/in.sdc" in before["files"]
    assert "phase2/stage2/constraints/in.sdc" in after["files"]
    assert before["files"]["phase2/stage2/constraints/in.sdc"] != \
        after["files"]["phase2/stage2/constraints/in.sdc"]
    assert producer._is_run_owned_evidence(tmp_path, source) is False
    assert producer._target_digest(source) is None
