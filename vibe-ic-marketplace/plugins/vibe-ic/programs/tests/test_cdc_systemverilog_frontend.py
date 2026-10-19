"""Native CDC input frontend: packaged SV, generate, selected top and legacy Verilog."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
FIXTURE = PROG / "tests/fixtures/cdc_netlist"
sys.path.insert(0, str(PROG))
import _cdc_netlist as cdc

pytestmark = pytest.mark.skipif(not shutil.which("yosys"), reason="native Yosys/slang required")


def project(root, unsafe=False):
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    for source in (FIXTURE / "sv_source_import").glob("*.sv"):
        shutil.copyfile(source, rtl / source.name)
    if unsafe:
        bridge = rtl / "a_bridge.sv"
        bridge.write_text("`define SHORT_PIPE\n" + bridge.read_text())
    l9 = root / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "neutral_bridge"}))
    return sorted(rtl.glob("*.sv"))


def crossing(root):
    output = root / "crossing-check.json"
    done = subprocess.run([sys.executable, str(PROG / "clock_domain_reg_crossing_check.py"),
        str(root), "--front-end", "netlist", "--json", str(output)],
        capture_output=True, text=True)
    return done.returncode, json.loads(output.read_text())


@pytest.mark.parametrize("unsafe,flops,rc,rules", [
    (False, 3, 0, []), (True, 2, 1, ["CDC_REG_NO_SYNC"]),
])
def test_packaged_generated_native_netlist_and_real_crossing(tmp_path, unsafe, flops, rc, rules):
    files = project(tmp_path, unsafe)
    before = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    try:
        native = cdc.build(tmp_path, files, "neutral_bridge")
        observed = {"status": "PASS", "reason": ""}
    except cdc.Refusal as error:
        observed = {"status": "FAIL", "reason": str(error)}
    assert observed["status"] == "PASS", observed
    netlist = cdc.load(native)
    cdc.require_binding(tmp_path, native, netlist)
    assert netlist.top == "neutral_bridge"
    assert len(netlist.flops) == flops
    assert cdc.clock_domains(netlist) == ["clk_aux_i", "clk_fast_i"]
    assert before == {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    actual_rc, report = crossing(tmp_path)
    actual_rules = sorted({row["rule"] for row in report["findings"] if row["severity"] == "ERROR"})
    assert (actual_rc, actual_rules) == (rc, rules), report
    assert report["summary"]["netlist_read"]
    assert report["summary"]["front_end"] == "netlist"


def test_missing_package_provider_leaves_no_prior_admission(tmp_path):
    files = project(tmp_path)
    (files[0].parent / "z_types.sv").unlink()
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_BUILD_FAILED"):
        cdc.build(tmp_path, [f for f in files if f.exists()], "neutral_bridge")
    assert not (tmp_path / cdc.NETLIST_REL).exists()
    assert not (tmp_path / cdc.NETLIST_MANIFEST_REL).exists()
    actual_rc, report = crossing(tmp_path)
    assert actual_rc == 1
    assert any(row["severity"] == "ERROR" for row in report["findings"])


def test_existing_plain_verilog_fixture_keeps_real_native_reader(tmp_path):
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "multi_clock_sync.v"
    shutil.copyfile(FIXTURE / "multi_clock_sync.v", source)
    native = cdc.build(tmp_path, [source], "multi_clock_sync")
    netlist = cdc.load(native)
    cdc.require_binding(tmp_path, native, netlist)
    assert cdc.clock_domains(netlist) == ["clk_a", "clk_b"]
    assert "read_verilog -sv -defer" in (tmp_path / cdc.NETLIST_LOG_REL).read_text()
    assert "read_slang" not in (tmp_path / cdc.NETLIST_LOG_REL).read_text()
    actual_rc, report = crossing(tmp_path)
    assert actual_rc == 0, report
