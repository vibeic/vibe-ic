"""Owner-local routing controls; a proof entry is not an equivalence result.

The optional current packet supplies unmodified RTL/netlist and actual library
logs. Otherwise neutral fixtures exercise the same public entry points. No
Docker process is executed, and no LEC PASS record is synthesized.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(os.environ.get("VIBEIC_LOCAL_OWNER_PROGRAMS",
                               str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import lec_run as L
import pdk_revision_resolve as P


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    packet = os.environ.get("VIBEIC_LOCAL_OWNER_CURRENT_PACKET")
    if packet:
        source = Path(packet)
        declaration = json.loads((source / "plugin_output/declaration.json").read_text())
        top = declaration["top_module"]
        for relative in ("phase2/stage1/rtl", "phase2/stage2/synth"):
            shutil.copytree(source / relative, root / relative)
        synthesis = source / "phase3/librelane/02-yosys-synthesis"
        for name in ("yosys-synthesis.log", "invocation.log", "COMMANDS"):
            destination = root / "phase3/librelane/02-yosys-synthesis" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(synthesis / name, destination)
        tree = json.loads((source / "reports/pdk_revision.json").read_text())["trees"][0]["tree"]
    else:
        top = "unit_core"
        rtl = root / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / f"{top}.v").write_text(
            f"module {top}(input a, output y); assign y=a; endmodule\n")
        synth = root / "phase2/stage2/synth"
        synth.mkdir(parents=True)
        shutil.copyfile(rtl / f"{top}.v", synth / f"{top}_synth.v")
        tree = str(tmp_path / "pdkstore/versions" / ("ab" * 20) / "process")
        library = Path(tree) / "libs.ref/cells/lib/typical.lib"
        library.parent.mkdir(parents=True)
        library.write_text("/* neutral library */\n")
        log = root / "phase3/librelane/synthesis/tool.log"
        log.parent.mkdir(parents=True)
        log.write_text(f"Executing Liberty frontend: {library}\n")
    return root, top, tree




def test_revision_cli_reads_current_tool_namespace(project):
    root, _, tree = project
    output = root / "reports/pdk_revision.json"
    rc = P.main(["--from-run", str(root), "--container", "named-eda-lane",
                 "--json", str(output)])
    assert rc == 0, output.read_text()
    record, error = P.load_record(root)
    assert error is None and record["resolved"], (record, error)
    assert record["read_in"] == "host"
    assert record["trees"][0]["resolved_tree"] == str(Path(tree).resolve())




def test_absent_local_tree_still_refuses(tmp_path):
    record = P.build_record([
        P.resolve_tree(P.Fs("named-eda-lane"), str(tmp_path / "absent"))],
        "host", "control")
    assert record["resolved"] is False and record["revision"] is None
    assert P.record_refusal(record) == P.REFUSAL_NOT_RECORDED




def test_native_marked_probe_keeps_watchdog_and_native_argv(tmp_path):
    """Real bounded capability probe, not a Yosys equivalence invocation."""
    if shutil.which("yosys") is None:
        pytest.skip("Yosys capability not installed")
    telemetry = tmp_path / "probe.telemetry.json"
    result = L._docker("host", "yosys -V", marker="yosys -V",
                       telemetry_path=telemetry)
    assert result.returncode == 0 and "Yosys" in result.stdout
    assert result.args[:2] == ["bash", "-lc"]
    record = json.loads(telemetry.read_text())
    assert len(record["attempts"]) == 1 and record["status"] == "complete"
