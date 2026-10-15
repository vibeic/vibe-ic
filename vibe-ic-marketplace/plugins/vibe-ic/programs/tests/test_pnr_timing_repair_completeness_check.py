"""Tests for pnr_timing_repair_completeness_check.py.

Covers the sta-review captured-note rule: a PnR Tcl that runs ONLY
`repair_timing -hold` (and not set_wire_rc + repair_design +
repair_timing -setup) is the sha256 silicon-DOA anti-pattern.
"""
import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import pnr_timing_repair_completeness_check as mod  # noqa: E402


# ---- canonical good PnR flow (mirrors the phase3 runner template) ----
GOOD_FLOW = """\
read_liberty sky130.lib
read_verilog design.v
link_design top
read_sdc design.sdc

if {[catch {set_wire_rc -signal -layer met1} _swr_sig]} {
  catch {set_wire_rc -layer met1}
}
catch {set_wire_rc -clock -layer met5}
catch {estimate_parasitics -placement}
catch {repair_design}
catch {repair_timing -setup}
catch {detailed_placement}

clock_tree_synthesis -buf_list {sky130_fd_sc_hd__clkbuf_4}
catch {repair_timing -hold}
detailed_placement

global_route
catch {estimate_parasitics -global_routing}
catch {repair_design}
catch {repair_timing -setup}
catch {repair_timing -hold}
detailed_placement
"""

# ---- the silicon-DOA anti-pattern: ONLY hold-repair ----
HOLD_ONLY_FLOW = """\
read_liberty sky130.lib
read_verilog design.v
link_design top
read_sdc design.sdc
global_placement
detailed_placement
clock_tree_synthesis -buf_list {sky130_fd_sc_hd__clkbuf_4}
repair_timing -hold
detailed_placement
global_route
detailed_route
"""

# ---- missing only the EXPECTED (estimate_parasitics + hold) -> WARN ----
SETUP_NO_HOLD_FLOW = """\
read_verilog design.v
link_design top
set_wire_rc -signal -layer met1
set_wire_rc -clock -layer met5
repair_design
repair_timing -setup
detailed_placement
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_pass_full_flow(tmp_path, capsys):
    """All 3 required commands present (even inside catch{}) -> PASS, exit 0."""
    p = _write(tmp_path, "pnr_good.tcl", GOOD_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["setup_repair_chain_present"] is True
    assert rep["summary"]["hold_repair_present"] is True
    assert rep["summary"]["missing_required"] == []
    assert rep["summary"]["hold_only_antipattern"] is False
    captured = capsys.readouterr()
    assert "PASS:" in captured.out


def test_fail_hold_only_antipattern(tmp_path, capsys):
    """repair_timing -hold but no setup chain -> FAIL, exit 1, antipattern flag."""
    p = _write(tmp_path, "pnr_hold_only.tcl", HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["summary"]["hold_only_antipattern"] is True
    assert rep["summary"]["setup_repair_chain_present"] is False
    # all 3 required are flagged missing
    missing = rep["summary"]["missing_required"]
    assert any("set_wire_rc" in m for m in missing)
    assert any("repair_design" in m for m in missing)
    assert any("repair_timing -setup" in m for m in missing)
    captured = capsys.readouterr()
    assert "hold_only_antipattern" in captured.out


def test_warn_setup_present_but_no_hold(tmp_path):
    """Setup chain present, but missing estimate_parasitics + hold -> WARN, exit 0."""
    p = _write(tmp_path, "pnr_warn.tcl", SETUP_NO_HOLD_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 0  # WARN is non-blocking
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "WARN"
    assert rep["summary"]["setup_repair_chain_present"] is True
    assert rep["summary"]["missing_required"] == []
    # estimate_parasitics + hold are the expected-missing ones
    me = rep["summary"]["missing_expected"]
    assert any("estimate_parasitics" in m for m in me)
    assert any("repair_timing -hold" in m for m in me)


def test_fail_missing_one_required(tmp_path):
    """Has set_wire_rc + repair_design but no repair_timing -setup -> FAIL."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "set_wire_rc -signal -layer met1\n"
        "repair_design\n"
        "repair_timing -hold\n"
        "detailed_placement\n"
    )
    p = _write(tmp_path, "pnr_partial.tcl", flow)
    rc = mod.main([str(p)])
    assert rc == 1
    verdict, findings, summary = mod.audit(p)
    assert verdict == "FAIL"
    assert any("repair_timing -setup" in m for m in summary["missing_required"])
    # not a hold-only antipattern because set_wire_rc + repair_design present
    assert summary["hold_only_antipattern"] is False


def test_commented_out_does_not_count(tmp_path):
    """A fully-commented repair_timing -setup line does NOT count as present."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "set_wire_rc -signal -layer met1\n"
        "repair_design\n"
        "# repair_timing -setup   ;# TODO turn this back on\n"
        "repair_timing -hold\n"
    )
    p = _write(tmp_path, "pnr_commented.tcl", flow)
    rc = mod.main([str(p)])
    assert rc == 1
    verdict, _, summary = mod.audit(p)
    assert verdict == "FAIL"
    assert any("repair_timing -setup" in m for m in summary["missing_required"])


def test_catch_guarded_counts_as_present(tmp_path):
    """A command wrapped in `catch {...}` still executes -> counts as present."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "catch {set_wire_rc -signal -layer met1}\n"
        "catch {repair_design}\n"
        "catch {repair_timing -setup}\n"
    )
    p = _write(tmp_path, "pnr_catch.tcl", flow)
    verdict, _, summary = mod.audit(p)
    assert summary["setup_repair_chain_present"] is True
    assert summary["missing_required"] == []


# ---- honest-FAIL edge cases: missing / empty / garbage input ----

def test_missing_file_is_error_not_pass(tmp_path, capsys):
    rc = mod.main([str(tmp_path / "nope.tcl")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_empty_file_is_error_not_pass(tmp_path, capsys):
    p = _write(tmp_path, "empty.tcl", "   \n  \n")
    rc = mod.main([str(p)])
    assert rc == 2
    assert "empty" in capsys.readouterr().err


def test_non_tcl_garbage_is_error_not_pass(tmp_path, capsys):
    """A file with no OpenROAD anchors must NOT vacuously PASS -> exit 2."""
    p = _write(tmp_path, "readme.txt",
               "This is a project README.\nIt has prose, no Tcl flow.\n")
    rc = mod.main([str(p)])
    assert rc == 2
    assert "no OpenROAD" in capsys.readouterr().err


# ---- DIRECTORY MODE (added when the gate was wired into Step 17) ----
#
# The gate is wired UNCONDITIONALLY on the P&R DIRECTORY, not on a literal
# `pnr.tcl`. Both halves are load-bearing and both are pinned here.

def test_directory_finds_a_differently_named_pnr_script(tmp_path):
    """The published run whose defect this gate exists for names its script
    `pnr_fixed.tcl`. A literal `pnr.tcl` wire would have missed exactly it."""
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr_fixed.tcl").write_text(HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["summary"]["hold_only_antipattern"] is True
    assert rep["script"].endswith("pnr_fixed.tcl")


def test_directory_takes_the_worst_verdict(tmp_path):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(GOOD_FLOW)
    (d / "pnr_eco.tcl").write_text(HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert len(rep["audited"]) == 2
    assert rep["verdict"] == "FAIL"


def test_directory_ignores_non_pnr_tcl_siblings(tmp_path):
    """`sta_one.tcl` / `magic_stream_out.tcl` live in the same directory and
    are not P&R flows; auditing them would be a FAIL for the wrong reason."""
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(GOOD_FLOW)
    (d / "magic_stream_out.tcl").write_text("gds write out.gds\n")
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 0
    assert len(json.loads(out.read_text())["audited"]) == 1


def test_directory_with_no_pnr_script_is_the_disclosed_skip_tier(tmp_path):
    """rc=2 is the flow's disclosed-skip tier. It is what lets this gate be
    wired UNCONDITIONALLY instead of behind a `condition_files_exist` on the
    very script whose absence would be interesting."""
    d = tmp_path / "pnr"
    d.mkdir()
    rc = mod.main([str(d)])
    assert rc == 2


def test_missing_directory_is_also_the_skip_tier(tmp_path):
    rc = mod.main([str(tmp_path / "no_such_dir")])
    assert rc == 2


# #3170: neutral interpreter/process fixtures exercise the whole owning hook,
# real produce_pnr, unchanged leaf CLI and single-gate canonical consumer.
# No OpenROAD/LibreLane native process or real benchmark is used here.
def _step17_native_receiver(tmp_path, monkeypatch, *, damage=None,
                            template_edit=None, fail_operation=None,
                            producer=None):
    import hashlib
    import importlib.util
    import shlex
    import subprocess
    import types
    import execution_backend_producers as actual_producer
    import librelane_contract as ll
    import flow_compliance_check as fcc

    producer = producer or actual_producer
    project = tmp_path / "neutral"
    project.mkdir(parents=True)
    image_scripts = tmp_path / "image-scripts"
    common = image_scripts / "openroad/common"
    common.mkdir(parents=True)
    # External image helper fixture: selected layer values must survive the
    # product's inlining and reach actual Tcl command dispatch.
    (common / "set_rc.tcl").write_text(
        "log_cmd set_wire_rc -signal -layer $::env(SIGNAL_WIRE_RC_LAYERS)\n"
        "log_cmd set_wire_rc -clock -layer $::env(CLOCK_WIRE_RC_LAYERS)\n")
    for name, text in {
        "io.tcl": "", "resizer.tcl": "",
        "dpl.tcl": "log_cmd detailed_placement\n",
    }.items():
        (common / name).write_text(text)
    harness = tmp_path / "primitive-fixture.tcl"
    harness.write_text(r'''
proc event {name args} {puts [linsert $args 0 $name]}
proc log_cmd {cmd args} {uplevel 1 [list $cmd {*}$args]}
proc read_current_odb {} {event read_current_odb}
proc all_clocks {} {return neutral_clock}
proc unset_propagated_clock {args} {event unset_propagated_clock {*}$args}
proc set_dont_touch_objects {} {event set_dont_touch_objects}
proc unset_dont_touch_objects {} {event unset_dont_touch_objects}
proc set_wire_rc {args} {event set_wire_rc {*}$args}
proc estimate_parasitics {args} {event estimate_parasitics {*}$args}
proc repair_design {args} {event repair_design {*}$args}
proc repair_timing {args} {
    event repair_timing {*}$args
    if {$::env(FAIL_OPERATION) eq "setup"} {error "NEUTRAL_SETUP_ERROR"}
}
proc detailed_placement {} {event detailed_placement}
proc write_views {} {event write_views}
if {[catch {source [lindex $argv 0]} message]} {
    puts stderr $message
    exit 1
}
''')
    runs = []

    class NativeBoundary:
        def get_command(self):
            return ["openroad-SOURCE_CONTROL", "-exit", self.get_script_path()]

        def run(self, state_in, **kwargs):
            import os
            command = self.get_command()
            folder = Path(self.step_dir)
            if damage == "other-executed-subject":
                other = folder / "old-executed.tcl"
                other.write_text(local_template.read_text().replace("log_cmd repair_timing -setup", ""))
                command[-1] = str(other)
            (folder / "COMMANDS").write_text(shlex.join(command) + "\n")
            env = dict(os.environ, SCRIPTS_DIR=str(image_scripts),
                       SIGNAL_WIRE_RC_LAYERS="neutral_signal", CLOCK_WIRE_RC_LAYERS="neutral_clock",
                       DESIGN_REPAIR_MAX_WIRE_LENGTH="0", DESIGN_REPAIR_MAX_SLEW_PCT="7",
                       DESIGN_REPAIR_MAX_CAP_PCT="9", FAIL_OPERATION=fail_operation or "")
            completed = subprocess.run(["tclsh", str(harness), command[-1]],
                                       env=env, text=True, capture_output=True)
            runs.append({"command": command, "subject_bytes": Path(command[-1]).read_bytes(),
                         "rc": completed.returncode, "stdout": completed.stdout,
                         "stderr": completed.stderr})
            (folder / "invocation.log").write_text(completed.stdout + completed.stderr)
            (folder / "SOURCE_CONTROL_TCL.json").write_text(json.dumps({
                "scope": "real Tcl interpreter, neutral OpenROAD primitive fixture; no EDA process",
                "rc": completed.returncode, "command": command,
                "subject_sha256": hashlib.sha256(Path(command[-1]).read_bytes()).hexdigest(),
                "stdout": completed.stdout, "stderr": completed.stderr}))
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            return {}, {}

    modules = {
        "librelane": types.ModuleType("librelane"),
        "librelane.common": types.ModuleType("librelane.common"),
        "librelane.steps": types.ModuleType("librelane.steps"),
        "librelane.steps.openroad": types.ModuleType("librelane.steps.openroad"),
        "librelane.steps.step": types.ModuleType("librelane.steps.step"),
    }
    modules["librelane.common"].get_script_dir = lambda: str(image_scripts)
    modules["librelane.steps.openroad"].RepairDesignPostGPL = NativeBoundary
    modules["librelane.steps.step"].Step = types.SimpleNamespace(
        factory=types.SimpleNamespace(register=lambda: lambda cls: cls))
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    source = Path(producer.__file__).parent / "librelane_plugins/librelane_plugin_vibeic/postgpl_fanout_closure.py"
    spec = importlib.util.spec_from_file_location("neutral_postgpl", source)
    hook_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_module)
    local_template = tmp_path / "template/postgpl_fanout_closure.tcl"
    local_template.parent.mkdir()
    body = source.with_suffix(".tcl").read_text()
    local_template.write_text(template_edit(body) if template_edit else body)
    # Only the template input boundary is substituted; the loaded product
    # class generates and runs its subject. No product function is copied.
    hook_module.__file__ = str(local_template.with_suffix(".py"))
    configs = {}
    by = {}
    image = "neutral-image@immutable"
    ids = ["OpenROAD.GlobalPlacement", "OpenROAD.RepairDesignPostGPL",
           "OpenROAD.DetailedPlacement"]
    monkeypatch.setattr(ll, "flow_segment", lambda *_: list(ids))
    monkeypatch.setattr(producer, "_parameters", lambda *_:
        (types.SimpleNamespace(), ll, types.SimpleNamespace(name="neutral"), "SOURCE_CONTROL"))

    def native_chain(_project, params, selected_ids, predecessor, overlay):
        # Native lane I/O is the SOURCE_CONTROL boundary. Actual hook.run,
        # producer export, native receipt validator and all consumers are real.
        for sid in selected_ids:
            folder = project / "phase3/librelane/current" / sid.replace(".", "-")
            folder.mkdir(parents=True)
            by[sid] = folder
            config = folder / "selected-config.json"
            config.write_text('{"selected":"neutral"}\n')
            configs[sid] = config
        sid = "Vibeic.PostGPLFanoutClosure"
        folder = by[sid]
        hook = hook_module.PostGPLFanoutClosure()
        hook.step_dir = str(folder)
        hook.run({})
        fp = {"step": sid, "image": image,
              "config": hashlib.sha256(configs[sid].read_bytes()).hexdigest()}
        (folder / "input_fingerprint.json").write_text(json.dumps(fp))
        (folder / "pdk_root.json").write_text('{"scope":"SOURCE_CONTROL"}')
        (folder / "state_out.json").write_text('{"metrics":{}}')
        # Mirrors the native I/O receipt's documented JSON/RPT persistence,
        # not the exporter implementation or its acceptance decision.
        bound = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in folder.iterdir() if p.suffix in (".json", ".rpt")}
        bound["invocation.log"] = hashlib.sha256((folder / "invocation.log").read_bytes()).hexdigest()
        (folder / "vibeic_receipt.json").write_text(json.dumps({"input": fp, "sha256": bound}))
        subject = Path(runs[-1]["command"][-1])
        if damage == "missing-subject":
            subject.unlink()
        elif damage == "changed-subject":
            subject.write_text(subject.read_text() + "# changed after execution\n")
        elif damage == "changed-command":
            (folder / "COMMANDS").write_text("openroad unrelated.tcl\n")
        elif damage == "missing-record":
            (folder / "pnr_postgpl_timing.json").unlink(missing_ok=True)
        elif damage == "wrong-image":
            params["image_id"] = "other-image@immutable"
        elif damage == "changed-config":
            configs[sid].write_text('{"selected":"different"}\n')
        elif damage == "stale-record":
            record = folder / "pnr_postgpl_timing.json"
            if record.is_file():
                record.write_text(record.read_text() + " ")
        return ll, configs, by

    monkeypatch.setattr(producer, "_state_chain", native_chain)

    def handoff(*_args):
        out = project / "phase3/stage3/pnr"
        out.mkdir(parents=True)
        (out / "placed.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
        return {"scope": "SOURCE_CONTROL native handoff"}

    monkeypatch.setattr(producer, "_handoff", handoff)
    result = producer.produce_pnr(project, {"step_id": "17", "top": "neutral", "image_id": image})
    row = {"id": "17", "name": "neutral selected native timing session", "required_outputs": [],
           "gate": {"program_exit_zero": "pnr_timing_repair_completeness_check phase3/stage3/pnr --json reports/phase3/pnr/timing_repair_completeness.json"}}
    leaf = subprocess.run([sys.executable, str(PROG_DIR / "pnr_timing_repair_completeness_check.py"),
                           "phase3/stage3/pnr", "--json", "leaf.json"],
                          cwd=project, capture_output=True, text=True)
    consumer = fcc.check_step(project, row, {})
    (project / "SOURCE_CONTROL_OBSERVATION.json").write_text(json.dumps({
        "scope": "real product hook/produce_pnr/export/leaf/single-gate consumer; native lane/state/handoff are fixtures",
        "producer": result, "leaf_rc": leaf.returncode, "leaf_stdout": leaf.stdout,
        "consumer_status": consumer.status,
        "runs": [{k: v for k, v in run.items() if k != "subject_bytes"} for run in runs]}, indent=2))
    return {"project": project, "runs": runs, "producer": result,
            "leaf_rc": leaf.returncode, "leaf_stdout": leaf.stdout,
            "consumer_status": consumer.status, "by": by, "configs": configs}


def test_step17_real_hook_subject_is_executed_exported_and_consumed(tmp_path, monkeypatch):
    obs = _step17_native_receiver(tmp_path, monkeypatch)
    assert obs["producer"]["verdict"] == "PASS"
    assert obs["leaf_rc"] == 0, obs
    assert obs["consumer_status"] == "PASS", obs
    run = obs["runs"][-1]
    exported = obs["project"] / "phase3/stage3/pnr/pnr_postgpl_timing.tcl"
    assert exported.read_bytes() == run["subject_bytes"]
    lines = run["stdout"].splitlines()
    operations = [line.split()[0] for line in lines]
    assert operations.index("set_wire_rc") < operations.index("estimate_parasitics") < operations.index("repair_design") < operations.index("repair_timing") < operations.index("detailed_placement")
    assert operations[operations.index("repair_timing") + 1] == "repair_design"
    assert "repair_timing -setup" in lines
    assert "set_wire_rc -signal -layer neutral_signal" in lines
    assert "set_wire_rc -clock -layer neutral_clock" in lines
    assert "repair_design -verbose -max_wire_length 0 -slew_margin 7 -cap_margin 9" in lines


@pytest.mark.parametrize("damage", ["missing-subject", "changed-subject", "changed-command",
                                   "missing-record", "wrong-image", "changed-config",
                                   "stale-record", "other-executed-subject"])
def test_step17_unbound_native_subject_is_refused(tmp_path, monkeypatch, damage):
    import execution_modes as em
    expected_named_refusal = "BACKEND_PLACEMENT_TIMING_SCRIPT_UNBOUND"
    with pytest.raises(em.Refusal):
        try:
            observed = _step17_native_receiver(tmp_path, monkeypatch, damage=damage)
        except em.Refusal as exc:
            assert exc.code == expected_named_refusal
            raise
        else:
            observed_outcome = (f"producer={observed['producer']['verdict']};"
                                f"leaf_rc={observed['leaf_rc']};"
                                f"consumer={observed['consumer_status']}")
            assert observed_outcome == expected_named_refusal
    assert not list((tmp_path / "neutral/phase3/stage3/pnr").glob("pnr*.tcl"))


@pytest.mark.parametrize("replacement", ["", "log_cmd repair_timing -hold"])
def test_step17_executed_missing_setup_or_hold_only_is_not_a_pass(tmp_path, monkeypatch, replacement):
    obs = _step17_native_receiver(tmp_path, monkeypatch,
        template_edit=lambda body: body.replace("log_cmd repair_timing -setup", replacement))
    assert obs["leaf_rc"] == 1, obs
    assert obs["consumer_status"] == "FAIL", obs


def test_step17_setup_error_stops_before_legalization_and_export(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="NEUTRAL_SETUP_ERROR"):
        try:
            observed = _step17_native_receiver(tmp_path, monkeypatch, fail_operation="setup")
        except RuntimeError:
            raise
        else:
            observed_outcome = (f"producer={observed['producer']['verdict']};"
                                f"leaf_rc={observed['leaf_rc']};"
                                f"consumer={observed['consumer_status']}")
            assert observed_outcome == "NEUTRAL_SETUP_ERROR"
    folder = tmp_path / "neutral/phase3/librelane/current/Vibeic-PostGPLFanoutClosure"
    log = (folder / "invocation.log").read_text()
    assert "repair_timing -setup" in log
    assert "detailed_placement" not in log and "write_views" not in log
    assert not (folder / "pnr_postgpl_timing.json").exists()
    assert not list((tmp_path / "neutral/phase3/stage3/pnr").glob("pnr*.tcl"))
