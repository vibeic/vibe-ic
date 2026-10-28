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


def population_native(root, top='cdc_population_mixed'):
    """Run the existing native build/normalization; no process substitution."""
    fixture = PROG / 'tests/fixtures/cdc_netlist/cdc_population.v'
    rtl = root / 'phase2/stage1/rtl/cdc_population.v'
    rtl.parent.mkdir(parents=True)
    shutil.copyfile(fixture, rtl)
    graph = cdc.build(root, [rtl], top)
    model = cdc.load(graph)
    binding = cdc.require_binding(root, graph, model)
    return model, binding


def test_native_population_includes_every_sync_and_unsync_endpoint(tmp_path):
    import hashlib
    model, binding = population_native(tmp_path)
    rc, report = ordinary(tmp_path)
    # Existing finding semantics stay calibrated and unchanged: the safe
    # crossing is omitted from findings, while the unsafe crossing fails.
    assert rc == 1 and report['summary']['errors'] == 1, report
    assert report['findings'] == cdc.judge(model, 'reg_crossing')
    assert report['findings'][0]['rule'] == 'CDC_REG_NO_SYNC'
    population = report['summary'].get('reg_crossing_population', {})
    assert population.get('status') == 'MEASURED', population
    doc = json.loads((tmp_path / cdc.NETLIST_REL).read_text())['modules'][model.top]

    def endpoint(net):
        q = doc['netnames'][net]['bits']
        return next((name, cell) for name, cell in doc['cells'].items()
                    if cell['connections'].get('Q') == q)

    expected = []
    for source, destination, synchronised in (
            ('launch_safe', 'sync1', True), ('launch_unsafe', 'capture_unsafe', False)):
        sender, scell = endpoint(source)
        receiver, dcell = endpoint(destination)
        expected.append({'source_cell': sender, 'source_q_index': 0,
            'source_q_bit': scell['connections']['Q'][0],
            'destination_cell': receiver, 'destination_d_index': 0,
            'destination_d_bit': dcell['connections']['D'][0],
            'from_domain': 'clk_a', 'to_domain': 'clk_b',
            'direct': True, 'synchronised': synchronised})
    actual = population['crossings']
    assert sorted(actual, key=json.dumps) == sorted(expected, key=json.dumps), {
        'actual': actual, 'expected': expected}
    assert population['traversal_complete'] is True
    assert population['source_q_bits_examined'] == population['destination_d_bits'] == 5
    assert population['input_fingerprint'] == binding['input']['fingerprint']
    assert population['producer'] == binding['producer']
    assert population['netlist']['sha256'] == hashlib.sha256(
        (tmp_path / cdc.NETLIST_REL).read_bytes()).hexdigest()
    assert population['checker_sha256'] == hashlib.sha256(Path(cdc.__file__).read_bytes()).hexdigest()


def test_native_single_domain_population_is_empty_after_complete_traversal(tmp_path):
    model, _binding = population_native(tmp_path, 'cdc_population_single')
    rc, report = ordinary(tmp_path)
    assert rc == 0 and report['findings'] == [], report
    population = report['summary'].get('reg_crossing_population', {})
    assert population.get('status') == 'MEASURED', population
    assert population['clock_domains'] == ['clk']
    assert population['crossings'] == [] and population['traversal_complete'] is True
    assert population['source_q_bits_examined'] == population['destination_d_bits'] == len(model.flops) == 2


@pytest.mark.parametrize('damage', ['missing', 'stale', 'unreadable', 'no_decoded_flops'])
def test_unproven_native_population_cannot_be_measured_empty(tmp_path, damage):
    population_native(tmp_path, 'cdc_population_comb' if damage == 'no_decoded_flops'
                      else 'cdc_population_mixed')
    path = tmp_path / cdc.NETLIST_REL
    if damage == 'missing':
        path.unlink()
    elif damage == 'stale':
        rtl = tmp_path / 'phase2/stage1/rtl/cdc_population.v'
        rtl.write_text(rtl.read_text() + '// changed native input\n')
    elif damage == 'unreadable':
        path.write_text('not a native JSON graph\n')
    rc, report = ordinary(tmp_path)
    population = report['summary'].get('reg_crossing_population', {})
    assert population.get('status') == 'NOT_MEASURED', report
    assert 'crossings' not in population, population
    if damage != 'no_decoded_flops':
        assert rc != 0 and report['summary']['netlist_read'] is False, report


def test_regex_findings_do_not_authorize_native_population(tmp_path):
    population_native(tmp_path)
    from clock_domain_reg_crossing_check import audit
    report = audit(project_dir=str(tmp_path), front_end='regex')
    assert report.summary['reg_crossing_population']['status'] == 'NOT_MEASURED'


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


def legacy_consumers(self, source_bit, exclude_domain=None):
    """Independent original relation, including the original uncached cones."""
    rows = []
    for flop in self.nl.flops:
        if exclude_domain is not None and self.domain(flop) == exclude_domain:
            continue
        skip = {flop.srst} if flop.srst is not None else None
        for index, bit in enumerate(flop.d):
            qbits, pbits = self.nl.cone([bit], skip=skip,
                                      q_of=self.q_of, ports=self.port_bits)
            if source_bit in qbits | pbits:
                rows.append((flop, index, self.nl.direct_source(
                    flop, index, ports=self.port_bits) == source_bit))
    return rows


def assert_ordered_judges_equal(model, monkeypatch):
    current = [cdc.judge(model, rule, lambda _name: True)
               for rule in ("reg_crossing", "async_input", "reset_dependency")]
    with monkeypatch.context() as patch:
        patch.setattr(cdc._LookupSnapshot, "cone", legacy_cone)
        patch.setattr(cdc._LookupSnapshot, "consumers", legacy_consumers)
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
                cell["connections"][pin] = CountingList(conn, work)
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


def test_consumer_relation_retains_destinations_without_dense_source_product():
    model, _work = vector_model(32)
    lookup = cdc._LookupSnapshot(model)
    for source in [*model.flops[0].q, *model.ports["data"][1], 99999]:
        assert lookup.consumers(source) == legacy_consumers(lookup, source)
    # Measure retained relation entries under either representation, so the
    # current dense implementation fails on an observed value, not a new API.
    relation = getattr(lookup, "_consumer_groups", None)
    if relation is None:
        relation = lookup._consumers
    retained = sum(len(group) for group in relation.values())
    destinations = sum(len(flop.d) for flop in model.flops)
    assert retained <= destinations, {"retained": retained, "destinations": destinations}


@pytest.mark.parametrize("fixture,program,expected", [
    ("cdc_sync", "clock_domain_reg_crossing_check", 0),
    ("cdc_unsync", "clock_domain_reg_crossing_check", 1),
    ("async_raw_sync", "cdc_async_input_check", 0),
    ("async_raw_unsync", "cdc_async_input_check", 1),
    ("reset_sync_ok", "reset_dependency_check", 0),
    ("reset_circular", "reset_dependency_check", 1),
])
def test_compact_relation_native_three_consumer_controls(tmp_path, fixture, program, expected):
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                          "calibration", "cdc_netlist_" + fixture + ".v")
    rtl = tmp_path / "phase2/stage1/rtl" / source.name
    rtl.parent.mkdir(parents=True)
    rtl.write_bytes(source.read_bytes())
    netlist = cdc.build(tmp_path, [rtl], fixture)
    cdc.require_binding(tmp_path, netlist, cdc.load(netlist))
    report = tmp_path / "ordinary.json"
    argv = [sys.executable, str(PROG / (program + ".py")), str(tmp_path),
            "--front-end", "netlist", "--json", str(report)]
    completed = subprocess.run(argv, capture_output=True, text=True)
    receipt = {"argv": argv, "rc": completed.returncode, "stdout": completed.stdout,
               "stderr": completed.stderr, "report": json.loads(report.read_text())}
    (tmp_path / "ordinary-native-receipt.json").write_text(json.dumps(receipt, indent=2))
    assert completed.returncode == expected, receipt
    errors = [row for row in receipt["report"]["findings"] if row["severity"] == "ERROR"]
    assert bool(errors) == bool(expected), receipt
