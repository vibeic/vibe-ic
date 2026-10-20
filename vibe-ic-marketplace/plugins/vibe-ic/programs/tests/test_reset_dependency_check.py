"""Unit tests for reset_dependency_check.py.

Tests verify correct detection of circular reset dependencies via
reset-combining assigns, clean reset chains that should pass, trivial
designs without reset chains, and empty directories.
"""
import sys
from pathlib import Path

# R-0929-TOOL-DEFAULT (owner, 2026-09-29): the step-3 default front end is the
# Yosys JSON netlist. These tests pin the REGEX front end's behaviour, which is
# kept and selectable (HARVEST-then-delete amendment), so each call names it
# (`front_end="regex"`); the assertions are unchanged. The netlist-arm lessons
# are pinned in test_t91_step3_cdc_netlist_front_end.py.


import pytest

SCRIPT = Path(__file__).parent.parent / 'reset_dependency_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import reset_dependency_check as rdc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Clean reset chain → PASS
#   drst produces sys_rstn from POR_BO.
#   otp_ctrl is reset by por_sync_out (not sys_rstn) — no cycle.
# ---------------------------------------------------------------------------
def test_clean_reset_chain_passes(tmp_path):
    verilog = """\
module top (
    input  wire clk,
    input  wire POR_BO,
    output wire otp_done
);
    wire sys_rstn;
    wire por_sync_out;

    drst u_drst (
        .clk          (clk),
        .por_in       (POR_BO),
        .por_sync_out (por_sync_out),
        .sys_rstn     (sys_rstn)
    );

    otp_ctrl u_otp (
        .clk      (clk),
        .rstn     (por_sync_out),
        .otp_done (otp_done)
    );
endmodule
"""
    (tmp_path / "top.v").write_text(verilog)

    result = rdc.audit(str(tmp_path), front_end="regex")
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 2: Circular dependency → FAIL
#   assign sys_rstn = por & otp_done;
#   otp_ctrl instantiated with .rstn(sys_rstn) and produces otp_done
# ---------------------------------------------------------------------------
def test_circular_dep_fails(tmp_path):
    verilog = """\
module top (
    input  wire clk,
    input  wire por,
    output wire otp_done
);
    wire sys_rstn;

    assign sys_rstn = por & otp_done;

    otp_ctrl u_otp (
        .clk      (clk),
        .rstn     (sys_rstn),
        .otp_done (otp_done)
    );
endmodule
"""
    (tmp_path / "top.v").write_text(verilog)

    result = rdc.audit(str(tmp_path), front_end="regex")
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "CIRCULAR_RESET_DEPENDENCY"]
    assert len(errors) >= 1
    assert any("sys_rstn" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 3: Trivial design with no reset chain → PASS
# ---------------------------------------------------------------------------
def test_no_reset_chain_passes(tmp_path):
    verilog = """\
module trivial (
    input  wire       clk,
    input  wire       rstn,
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            q <= 8'h00;
        else
            q <= d;
    end
endmodule
"""
    (tmp_path / "trivial.v").write_text(verilog)

    result = rdc.audit(str(tmp_path), front_end="regex")
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 4: Empty directory → PASS
# ---------------------------------------------------------------------------
def test_empty_dir_passes(tmp_path):
    result = rdc.audit(str(tmp_path), front_end="regex")
    assert result.passed is True
    assert result.summary["files_scanned"] == 0
    assert result.summary["violations"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


def _native_reset_graph(root, kind, width):
    """Fresh native ARST-only fixtures; no captured JSON or inferred SRST."""
    import json
    import _cdc_netlist as cn
    rtl = root / "phase2/stage1/rtl/neutral_reset_top.v"
    rtl.parent.mkdir(parents=True)
    lines = [f"module neutral_reset_top(input wire clk, ext_rst, "
             f"input wire [{width-1}:0] data_i, output reg [{width-1}:0] q);"]
    for i in range(width):
        if kind == "no_resets":
            lines.append(f"always @(posedge clk) q[{i}] <= data_i[{i}];")
            continue
        if kind == "dense":
            deps = [j for j in range(width) if j != i]
        elif kind == "disjoint":
            base = (i // 3) * 3
            deps = [base + (i + 1 - base) % 3]
        elif kind == "broken" or kind == "dag":
            deps = [i + 1] if i + 1 < width else []
        else:
            deps = [(i + 1) % width]
        rhs = "ext_rst" + "".join(f" | q[{j}]" for j in deps)
        lines.extend([f"wire rst_{i} = {rhs};",
                      f"always @(posedge clk or posedge rst_{i}) "
                      f"if (rst_{i}) q[{i}] <= 1'b0; else q[{i}] <= data_i[{i}];"])
    rtl.write_text("\n".join(lines + ["endmodule"]) + "\n")
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "neutral_reset_top"}))
    path = cn.build(root, [rtl], "neutral_reset_top")
    model = cn.load(path)
    cn.require_binding(root, path, model)
    assert len(model.flops) == width
    assert all(f.srst is None for f in model.flops)
    assert all((f.arst is None) == (kind == "no_resets") for f in model.flops)
    lookup = cn._LookupSnapshot(model)
    reset_of = {f.name: {model.root(f.arst)} for f in model.flops
                if f.arst is not None}
    edges = {r: set() for roots in reset_of.values() for r in roots}
    for target in edges:
        qbits, _ports = model.cone([target])
        for bit in qbits:
            for source in reset_of.get(lookup.q_of[bit].name, ()):
                edges[source].add(target)
    return rtl, model, edges


def _ordinary_native_reset(root):
    import json
    import subprocess
    output = root / "ordinary_reset.json"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--front-end", "netlist",
         "--json", str(output)], capture_output=True, text=True)
    assert output.is_file(), done.stdout + done.stderr
    return done.returncode, json.loads(output.read_text())


@pytest.mark.parametrize("kind,width,components", [
    ("ring", 4, 1), ("ring", 17, 1), ("dense", 5, 1),
    ("ring", 1, 1), ("disjoint", 6, 2), ("broken", 17, 0),
    ("dag", 5, 0), ("no_resets", 3, 0),
])
def test_native_reset_complete_cycles_and_bounded_witnesses(tmp_path, kind, width, components):
    _rtl, _model, edges = _native_reset_graph(tmp_path, kind, width)
    rc, doc = _ordinary_native_reset(tmp_path)
    # These are actual values on the public consumer: the old depth cut misses
    # ring17, and the old enumeration reports 26 vertex sets for dense5.
    assert rc == int(components > 0), doc
    assert len(doc["findings"]) == components, doc
    assert doc["passed"] is (components == 0)
    assert all(f["rule"] == "CIRCULAR_RESET_DEPENDENCY" and
               f["severity"] == "ERROR" for f in doc["findings"])
    meta = doc["summary"].get("reset_dependency_analysis", {})
    assert meta, "the reporting policy must disclose witness rather than all-cycle counts"
    assert meta["reporting_policy"] == "one_witness_per_cyclic_scc"
    assert meta["cycle_detection_complete"] is True
    assert meta["all_cycles_enumerated"] is False
    assert meta["graph_scope"] == "existing_modeled_arst_srst_dependency_graph"
    assert meta["reset_role_policy"] == "unchanged_arst_srst_outer_mux_model"
    assert meta["native_reset_role_coverage"] == "not_assessed_by_cycle_detection"
    assert meta["reset_nodes"] == len(edges)
    edge_count = sum(map(len, edges.values()))
    assert meta["reset_edges"] == edge_count
    assert meta["reported_witnesses"] == meta["cyclic_scc_count"] == components
    for component in meta["cyclic_components"]:
        witness = component["witness_bits"]
        assert witness[0] == witness[-1]
        assert all(right in edges[left] for left, right in zip(witness, witness[1:]))
        assert set(witness) <= set(component["member_bits"])
    work = meta["work"]
    assert work["forward_edges_examined"] == edge_count
    assert work["reverse_edges_examined"] == edge_count
    assert work["witness_edges_examined"] <= edge_count
    assert work["forward_nodes_finished"] == work["reverse_nodes_visited"] == len(edges)


def test_native_reset_stale_binding_remains_blocking_without_complete_claim(tmp_path):
    rtl, _model, _edges = _native_reset_graph(tmp_path, "ring", 4)
    rtl.write_text(rtl.read_text() + "// current source changed after production\n")
    rc, doc = _ordinary_native_reset(tmp_path)
    assert rc == 1
    assert doc["passed"] is False
    assert doc["findings"]
    assert all(f["rule"] != "CIRCULAR_RESET_DEPENDENCY" for f in doc["findings"])
    assert "reset_dependency_analysis" not in doc["summary"]


def test_reset_cycle_witnesses_are_complete_and_deterministic_on_small_graphs():
    import _cdc_netlist as cn
    class ReverseSet(set):
        def __iter__(self):
            return iter(sorted(super().__iter__(), reverse=True))
    # Independent reachability closure classifies every graph on three nodes;
    # input iteration reversals must preserve the complete metadata/witnesses.
    for bits in range(1 << 9):
        edges = {v: {w for w in range(3) if bits & (1 << (3*v+w))}
                 for v in range(3)}
        reach = {v: set(edges[v]) for v in edges}
        for via in range(3):
            for start in range(3):
                if via in reach[start]:
                    reach[start] |= reach[via]
        unseen = set(edges)
        expected_cyclic = 0
        expected_sccs = 0
        while unseen:
            root = min(unseen)
            component = {v for v in unseen if v == root or
                         (v in reach[root] and root in reach[v])}
            unseen -= component
            expected_sccs += 1
            expected_cyclic += len(component) > 1 or root in edges[root]
        first = cn._reset_cycle_analysis(edges, str)
        reverse = cn._reset_cycle_analysis(
            {v: ReverseSet(edges[v]) for v in reversed(list(edges))}, str)
        assert first == reverse
        witnesses, meta = first
        assert len(witnesses) == expected_cyclic
        assert meta["scc_count"] == expected_sccs
        assert meta["cycle_detection_complete"] is True
        edge_count = sum(map(len, edges.values()))
        assert meta["work"]["forward_edges_examined"] == edge_count
        assert meta["work"]["reverse_edges_examined"] == edge_count
        assert meta["work"]["witness_edges_examined"] <= edge_count
        assert meta["work"]["forward_nodes_finished"] == 3
        assert meta["work"]["reverse_nodes_visited"] == 3
        for witness in witnesses:
            assert all(right in edges[left] for left, right in
                       zip(witness, witness[1:] + witness[:1]))
