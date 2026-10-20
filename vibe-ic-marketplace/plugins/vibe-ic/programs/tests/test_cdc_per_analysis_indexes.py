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


class CountedConnection(list):
    def __init__(self, values, work):
        super().__init__(values)
        self.work = work

    def __iter__(self):
        for bit in super().__iter__():
            self.work[0] += 1
            yield bit


@pytest.mark.parametrize("width", [16, 32, 64])
def test_native_shared_vector_cones_read_connections_once(tmp_path, width, record_property):
    rtl = tmp_path / "phase2/stage1/rtl/neutral_shared.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(f"""module neutral_shared(input clk_a, clk_b,
        input [{width-1}:0] data_i, salt0, salt1, salt2, salt3,
        output reg [{width-1}:0] data_o);
      reg [{width-1}:0] launch_q;
      wire [{width-1}:0] a = launch_q ^ salt0;
      wire [{width-1}:0] b = a ^ salt1;
      wire [{width-1}:0] c = b ^ salt2;
      wire [{width-1}:0] d = c ^ salt3;
      always @(posedge clk_a) launch_q <= data_i;
      always @(posedge clk_b) data_o <= d;
    endmodule
    """)
    output = cdc.build(tmp_path, [rtl], "neutral_shared")
    model = cdc.load(output)
    cdc.require_binding(tmp_path, output, model)
    expected = cdc.judge(model, "reg_crossing")
    rc, report = ordinary(tmp_path)
    assert rc == 1 and report["findings"] == expected
    assert len(expected) == 1 and expected[0]["rule"] == "CDC_REG_NO_SYNC"

    work = [0]
    budget = 0
    for cell in model.cells.values():
        if cell["type"] in cdc.FLOP_TYPES or cell["type"] in cdc._MEMORY:
            continue
        for pin, conn in cell["connections"].items():
            if cell["port_directions"][pin] != "output":
                budget += len(conn)
                cell["connections"][pin] = CountedConnection(conn, work)
    lookup = cdc._LookupSnapshot(model)
    cones = lookup.data_cones()
    for flop, index, sources in cones:
        expected_q, expected_p = model.cone(
            [flop.d[index]], skip={flop.srst} if flop.srst is not None else None)
        assert sources == expected_q | expected_p
    # The reference walks above intentionally do real work; measure a fresh
    # analysis alone and keep the complete relation, not a capped traversal.
    work[0] = 0
    second = cdc._LookupSnapshot(model).data_cones()
    assert second == cones
    record_property("connection_entries_read", work[0])
    record_property("native_input_connection_entries", budget)
    assert work[0] > 0
    assert work[0] == budget, {"observed": work[0], "expected": budget}


def test_shared_cones_close_cycles_and_keep_each_skip_context():
    # A<->B has exits on both nodes. C feeds that SCC. Resolving A then B
    # must not cache a partial cycle, and skipping one exit changes only that
    # context. The public uncached traversal is the independent reference.
    flop = cdc.Flop("sender", "$dff", 1, 1, [2, 3], [10, 11])
    cells = {
        "a": {"type": "$xor", "connections": {"A": [21, 10], "Y": [20]},
              "port_directions": {"A": "input", "Y": "output"}},
        "b": {"type": "$xor", "connections": {"A": [20, 11, 4], "Y": [21]},
              "port_directions": {"A": "input", "Y": "output"}},
        "c": {"type": "$xor", "connections": {"A": [20, "x", "z", "0", 99], "Y": [22]},
              "port_directions": {"A": "input", "Y": "output"}},
    }
    model = cdc.Netlist("neutral_cycle", {"inputs": ("input", [1, 2, 3, 4])},
                        cells, {}, {20: ("a", "Y"), 21: ("b", "Y"), 22: ("c", "Y")},
                        [flop])
    lookup = cdc._LookupSnapshot(model)
    for skip in (None, {10}, {11}, {20}, {21}, {4}, {10, 11}):
        for seeds in ([20], [21], [22], [99, "x"], [20, 21, 4]):
            assert lookup.cone(seeds, skip) == model.cone(seeds, skip)
    cells["a"]["connections"]["A"] = [3]
    # A new invocation snapshots the edited graph; no persistent graph cache.
    current = cdc._LookupSnapshot(model)
    for seeds in ([20], [21], [22]):
        assert current.cone(seeds) == model.cone(seeds)
    assert current.cone([20]) == (set(), {3})


def test_shared_cones_match_sparse_generated_graphs():
    import random

    for seed in range(12):
        rng = random.Random(seed)
        flop = cdc.Flop("sender", "$dff", 1, 1, [2, 3], [10, 11])
        cells, drivers = {}, {}
        for bit in range(20, 32):
            name = f"node{bit}"
            cells[name] = {"type": "$xor", "connections": {
                "A": rng.sample([2, 3, 10, 11, 99, "x", *range(20, 32)], 3),
                "Y": [bit]}, "port_directions": {"A": "input", "Y": "output"}}
            drivers[bit] = (name, "Y")
        model = cdc.Netlist("neutral_graph", {"inputs": ("input", [1, 2, 3])},
                            cells, {}, drivers, [flop])
        lookup = cdc._LookupSnapshot(model)
        for skip in (None, {10}, {21}, {3, 24}):
            for bit in range(20, 32):
                assert lookup.cone([bit], skip) == model.cone([bit], skip)


def test_shared_consumer_relation_preserves_order_and_direct_flags():
    flops = [cdc.Flop("sender", "$dff", 1, 1, [3, 4], [10, 11]),
             cdc.Flop("receiver", "$dff", 2, 1, [20, 10], [30, 31]),
             cdc.Flop("same_clock", "$dff", 1, 1, [20, 11], [40, 41]),
             cdc.Flop("receiver2", "$dff", 2, 1, [11, 20], [50, 51])]
    cell = {"type": "$xor", "connections": {"A": [10, 11, 3], "Y": [20]},
            "port_directions": {"A": "input", "Y": "output"}}
    model = cdc.Netlist("neutral_groups", {"inputs": ("input", [1, 2, 3, 4])},
                        {"mix": cell}, {}, {20: ("mix", "Y")}, flops)
    lookup = cdc._LookupSnapshot(model)
    for bit in [3, 4, 10, 11, 99, "x"]:
        expected = []
        for flop in flops:
            for index, target in enumerate(flop.d):
                q, p = model.cone([target])
                if bit in q | p:
                    expected.append((flop, index, model.direct_source(flop, index) == bit))
        assert lookup.consumers(bit) == expected
    # Reanalysis must reflect edits to the combinational input relation too.
    cell["connections"]["A"] = [4]
    current = cdc._LookupSnapshot(model)
    assert current.consumers(3) == [(flops[0], 0, True)]
    assert [f.name for f, _i, _d in current.consumers(10)] == ["receiver"]
