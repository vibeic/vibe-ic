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
    report = root / f"ordinary-{len(list(root.glob('ordinary-*.json')))}.json"
    argv = [sys.executable, str(PROG / "clock_domain_reg_crossing_check.py"),
            str(root), "--front-end", "netlist", "--json", str(report)]
    done = subprocess.run(argv, capture_output=True, text=True)
    report.with_suffix(".stdout").write_text(done.stdout)
    report.with_suffix(".stderr").write_text(done.stderr)
    report.with_suffix(".receipt").write_text(json.dumps({
        "argv": argv, "returncode": done.returncode}))
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


class CountingList(list):
    """Count actual input connection entries expanded by the owner."""
    def __init__(self, values, work):
        super().__init__(values)
        self.work = work

    def __iter__(self):
        for value in super().__iter__():
            self.work[0] += 1
            yield value


def vector_model(width, layers=4):
    work = [0]
    source = list(range(1000, 1000 + width))
    inputs = list(range(2000, 2000 + width))
    previous, cells, drivers = source, {}, {}
    for level in range(layers):
        outputs = list(range(3000 + 1000 * level, 3000 + 1000 * level + width))
        name = f"vector_logic_{level}"
        cells[name] = {"type": "$xor", "connections": {
            "A": CountingList(previous, work),
            "B": CountingList(["0"] * width, work), "Y": outputs},
            "port_directions": {"A": "input", "B": "input", "Y": "output"}}
        drivers.update({bit: (name, "Y") for bit in outputs})
        previous = outputs
    sender = cdc.Flop("sender", "$dff", 1, 1, inputs, source)
    receiver = cdc.Flop("receiver", "$dff", 2, 1, previous,
                        list(range(10000, 10000 + width)))
    return cdc.Netlist("neutral_vector", {
        "clk_a": ("input", [1]), "clk_b": ("input", [2]),
        "data": ("input", inputs)}, cells, {}, drivers, [sender, receiver]), work


@pytest.mark.parametrize("width", [8, 16, 32, 64])
def test_shared_vector_fanin_expands_connections_once(width):
    model, work = vector_model(width)
    lookup = cdc._LookupSnapshot(model)
    cones = lookup.data_cones()
    assert len(cones) == 2 * width
    expected = set(model.flops[0].q)
    assert all(cone == expected for flop, index, cone in cones
               if flop is model.flops[1])
    before = work[0]
    assert len(lookup.consumers(model.flops[0].q[0])) == width
    assert work[0] == before
    # The dense relation is still quadratic; only repeated input expansion
    # is bounded here. Four two-input vector cells each read 2*width entries.
    assert before <= 8 * width, {"width": width, "entries": before}


def legacy_cone(self, bits, skip=None):
    return self.nl.cone(bits, skip=skip, q_of=self.q_of, ports=self.port_bits)


def assert_ordered_judges_equal(model, monkeypatch):
    current = [cdc.judge(model, rule, lambda _name: True)
               for rule in ("reg_crossing", "async_input", "reset_dependency")]
    with monkeypatch.context() as patch:
        patch.setattr(cdc._LookupSnapshot, "cone", legacy_cone)
        previous = [cdc.judge(model, rule, lambda _name: True)
                    for rule in ("reg_crossing", "async_input", "reset_dependency")]
    assert current == previous  # complete ordered dictionaries, no sorting
    return current


def test_sparse_cyclic_unknown_frontiers_and_reset_cuts(monkeypatch):
    model, _work = vector_model(3, layers=2)
    # A cycle with exits to Q/input, an undriven bit, a constant, and a
    # memory frontier. Whole-vector output bits must share the same cone.
    model.cells["vector_logic_0"]["connections"]["A"].extend([4000, 2000, 99999])
    model.cells["memory"] = {"type": "$memrd", "connections": {"A": [1000]}}
    model.drivers[99999] = ("memory", "DATA")
    model.flops[1].srst = 3001
    for skip in (None, {3001}, {3000}, {1000}, {2000}):
        lookup = cdc._LookupSnapshot(model)
        for bit in (4000, 3000, 3001, 2000, 99999, 88888, "x", 1000):
            assert lookup.cone([bit], skip=skip) == model.cone([bit], skip=skip)
        assert lookup.cone([4000, 88888, "1"], skip=skip) == \
            model.cone([4000, 88888, "1"], skip=skip)
    assert_ordered_judges_equal(model, monkeypatch)
    model.flops[1].d[:] = [2000, 2001, 2002]
    assert_ordered_judges_equal(model, monkeypatch)
    model.flops[1].clk = 1
    assert assert_ordered_judges_equal(model, monkeypatch)[0] == []


def test_captured_cdc_rdc_complete_ordered_outputs(monkeypatch):
    fixture = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                           "programs", "tests", "fixtures", "cdc_netlist")
    calibration = PROG / "calibration"
    files = sorted(fixture.glob("*.json")) + sorted(calibration.glob("cdc_netlist_*.json"))
    assert files
    for path in files:
        assert_ordered_judges_equal(cdc.load(path), monkeypatch)


@pytest.mark.parametrize("width", [2, 5])
@pytest.mark.parametrize("safe", [True, False])
def test_native_vector_producer_and_ordinary_consumer(tmp_path, monkeypatch, width, safe):
    rtl = tmp_path / "phase2/stage1/rtl/neutral_vector.v"
    rtl.parent.mkdir(parents=True)
    expression = "launch_q" if safe else "(launch_q ^ (launch_q << 1))"
    tail = "reg [%d:0] stage2_q; always @(posedge clk_b) stage2_q <= stage1_q; assign data_o = stage2_q;" % (width - 1) \
        if safe else "assign data_o = stage1_q;"
    rtl.write_text(f"""module neutral_vector(input clk_a, clk_b,
      input [{width-1}:0] data_i, output [{width-1}:0] data_o);
      reg [{width-1}:0] launch_q, stage1_q;
      always @(posedge clk_a) launch_q <= data_i;
      always @(posedge clk_b) stage1_q <= {expression};
      {tail}
    endmodule\n""")
    netlist = cdc.build(tmp_path, [rtl], "neutral_vector")
    model = cdc.load(netlist)
    cdc.require_binding(tmp_path, netlist, model)
    rc, report = ordinary(tmp_path)
    assert rc == (0 if safe else 1), report
    assert report["findings"] == assert_ordered_judges_equal(model, monkeypatch)[0]
    assert any(row["rule"] == "CDC_REG_NO_SYNC" and row["severity"] == "ERROR"
               for row in report["findings"]) == (not safe)


def test_native_header_authority_and_genuine_dependency_invalidation(tmp_path):
    model = native(tmp_path, True)
    assert ordinary(tmp_path)[0] == 0
    binding = cdc.source_binding(tmp_path, "neutral_cdc")
    scratch = tmp_path / "verification/scratch.svh"
    scratch.parent.mkdir()
    scratch.write_text("`define UNUSED_SCRATCH 0\n")
    added_rc, added = ordinary(tmp_path)
    scratch.write_text("`define UNUSED_SCRATCH 1\n")
    edited_rc, edited = ordinary(tmp_path)
    scratch.unlink()
    assert ordinary(tmp_path)[0] == 0
    # Record both real public consumer observations before checking equality.
    assert (added_rc, edited_rc) == (0, 0), (added, edited)
    assert cdc.source_binding(tmp_path, "neutral_cdc") == binding
    assert model.top == "neutral_cdc"


@pytest.mark.parametrize("location", ["canonical", "declared_external"])
def test_native_real_header_options_top_and_partial_inputs_still_refuse(tmp_path, location):
    native(tmp_path, True)
    rtl = tmp_path / "phase2/stage1/rtl/neutral_cdc.sv"
    directory = rtl.parent if location == "canonical" else tmp_path / "verification"
    directory.mkdir(exist_ok=True)
    header = directory / "defs.svh"
    header.write_text("`define NEUTRAL_ZERO 0\n")
    rtl.write_text(f'`include "{header}"\n' + rtl.read_text())
    netlist = cdc.build(tmp_path, [rtl], "neutral_cdc")
    assert ordinary(tmp_path)[0] == 0
    header.write_text("`define NEUTRAL_ZERO 1\n")
    rc, report = ordinary(tmp_path)
    assert rc == 1 and any(r["rule"] == "CDC_NETLIST_STALE" for r in report["findings"])
    header.write_text("`define NEUTRAL_ZERO 0\n")
    assert ordinary(tmp_path)[0] == 0
    before = cdc.source_binding(tmp_path, "neutral_cdc")
    assert cdc.source_binding(tmp_path, None) != before
    switch = tmp_path / "phase3/librelane_switch.json"
    switch.parent.mkdir()
    switch.write_text(json.dumps({"steps": {"3": "librelane"}}))
    assert cdc.source_binding(tmp_path, "neutral_cdc") != before
    switch.unlink()
    rtl.write_text("`define LOCAL_VALUE 1\n" + rtl.read_text())
    assert ordinary(tmp_path)[0] == 1
    assert cdc.source_binding(tmp_path, "neutral_cdc") != before
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_PARTIAL_SOURCES"):
        cdc.source_binding(tmp_path, "neutral_cdc", [])
    l9 = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "different_top"}))
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_TOP_MISMATCH"):
        cdc.require_binding(tmp_path, netlist, cdc.load(netlist))
