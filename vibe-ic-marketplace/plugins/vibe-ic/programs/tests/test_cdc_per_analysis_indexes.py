"""Native CDC semantics, bounded lookup work, and fresh repeated analyses."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))
import _cdc_netlist as cdc
from _hostpaths import require_repo

pytestmark = pytest.mark.skipif(not shutil.which("yosys"), reason="native Yosys required")


class CountedPorts(dict):
    def __init__(self, ports):
        super().__init__(ports)
        self.walks = 0

    def items(self):
        self.walks += 1
        return super().items()


def native(root, safe, controlled=False):
    rtl = root / "phase2/stage1/rtl/neutral_cdc.sv"
    rtl.parent.mkdir(parents=True)
    reset = " or negedge rst_n" if controlled else ""
    source = ("if (!rst_n) launch_q <= 0; "
              "else if (enable_i) launch_q <= data_i[g];") \
        if controlled else "launch_q <= data_i[g];"
    first = ("if (!rst_n) stage1_q <= 0; "
             "else if (enable_i) stage1_q <= launch_q;") \
        if controlled else "stage1_q <= launch_q;"
    second = "if (!rst_n) stage2_q <= 0; else stage2_q <= stage1_q;" \
        if controlled else "stage2_q <= stage1_q;"
    tail = (f"reg stage2_q; always @(posedge clk_recv_i{reset}) {second} "
            "assign data_o[g] = stage2_q;") \
        if safe else "assign data_o[g] = stage1_q;"
    rtl.write_text(f"""module neutral_cdc(input clk_send_i, clk_recv_i, rst_n, enable_i,
        input [7:0] data_i, output [7:0] data_o);
      genvar g; generate for (g=0; g<8; g=g+1) begin: lane
        reg launch_q; reg stage1_q;
        always @(posedge clk_send_i{reset}) {source}
        always @(posedge clk_recv_i{reset}) {first}
        {tail}
      end endgenerate
    endmodule
    """)
    output = cdc.build(root, [rtl], "neutral_cdc")
    model = cdc.load(output)
    cdc.require_binding(root, output, model)
    return model


def ordinary(root):
    report = root / "ordinary.json"
    done = subprocess.run(
        [sys.executable, str(PROG / "clock_domain_reg_crossing_check.py"),
         str(root), "--front-end", "netlist", "--json", str(report)],
        capture_output=True, text=True)
    return done.returncode, json.loads(report.read_text())


@pytest.mark.parametrize("safe", [True, False])
@pytest.mark.parametrize("controlled", [False, True])
def test_native_semantics_without_rebuilding_port_maps_per_pair(tmp_path, safe, controlled):
    model = native(tmp_path, safe, controlled)
    rc, report = ordinary(tmp_path)
    assert rc == (0 if safe else 1), report
    assert report["summary"]["errors"] == (0 if safe else 8)
    model.ports = CountedPorts(model.ports)
    findings = cdc.judge(model, "reg_crossing")
    assert findings == report["findings"]
    # Input membership and all-port labels each require exactly one snapshot.
    # This is an operation count, not a flaky wall-time assertion.
    assert model.ports.walks == 2, {"full_port_walks": model.ports.walks}


def test_reanalysis_recomputes_current_data_dependencies(tmp_path):
    model = native(tmp_path, True)
    second = cdc.judge(model, "reg_crossing")
    assert len(second) == 0, second
    source_q = {q for f in model.flops
                if model.domain(f) == "clk_send_i" for q in f.q}
    changed = 0
    for flop in model.flops:
        if model.domain(flop) != "clk_recv_i":
            continue
        for i in range(len(flop.d)):
            if model.direct_source(flop, i) in source_q:
                flop.d[i] = model.ports["data_i"][1][0]
                model.cells[flop.name]["connections"]["D"][i] = flop.d[i]
                changed += 1
    assert changed == 8
    # Both domains remain; no receiving register now samples a sending Q bit.
    second = cdc.judge(model, "reg_crossing")
    assert len(second) == 0, second


def test_reanalysis_uses_current_clock_port_labels():
    captured = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "cdc_netlist", "cdc_via_submodule.json")
    model = cdc.load(captured)
    first = cdc.judge(model, "reg_crossing")
    assert len(first) == 1
    model.ports["replacement_clock_i"] = model.ports.pop("clk_b")
    second = cdc.judge(model, "reg_crossing")
    assert len(second) == 1
    assert {r["evidence"]["to_domain"] for r in second} == \
        {"replacement_clock_i"}
    assert all(r["rule"] == "CDC_REG_NO_SYNC"
               and r["severity"] == "ERROR" for r in second)
