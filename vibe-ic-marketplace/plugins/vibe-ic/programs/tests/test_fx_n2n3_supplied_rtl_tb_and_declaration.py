"""N2 / N3 — a design that SUPPLIES its RTL, on a core-only (no chip_top) run.

MEASURED on a supplied-RTL run whose top instantiates its only child as an
instance ARRAY (`leaf u[N-1:0] (...)`), core-only deliverable:

  N2  the orchestrator resolved the top BEFORE phase 2 staged the supplied RTL,
      saw an empty rtl/, and kept `chip_top`, a module the design does not have.
      The unit-TB producer then fell back to the instantiation-graph root, but
      its instance regex could not see an array instance, so it found two
      roots, refused as "ambiguous", and emitted no unit TB.
  N3  nothing wrote `plugin_output/declaration.json` on the supplied-RTL path,
      so the required-artifact gate reported the file ABSENT, although the flow
      knew the staged files, the top and its ports.

Every test drives the real function. Module, port and case names are generic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import testbench_gen as TBG                      # noqa: E402

EMITTER = _PROGRAMS / "spec_declaration_emit.py"
DECL_PATH = "plugin_output/declaration.json"

# The top instantiates its only child as an instance ARRAY, the child's ports
# are driven from a generate loop, and a parameter sizes both.
ARRAY_TOP = """\
module shift_top #(parameter n = 4) (
    input clk,
    input rst,
    input d,
    input [n-1:0] w,
    output q
);
    wire [n:0] chain;
    assign chain[0] = d;
    assign q = chain[n];
    wire [n-1:0] w_rev;
    genvar i;
    generate
        for (i = 0; i < n; i = i + 1) begin : rev
            assign w_rev[i] = w[n - i - 1];
        end
    endgenerate

    cell_stage stg[n-1:0](
        .clk(clk), .rst(rst), .w(w_rev),
        .din(chain[n-1:0]), .dout(chain[n:1])
    );
endmodule

module cell_stage(
    input clk,
    input rst,
    input w,
    input din,
    output reg dout
);
    always @(posedge clk or negedge rst)
        if (!rst) dout <= 1'b0; else dout <= din ^ w;
endmodule
"""

L10 = {"test_cases": [
    {"name": "tc_shift", "kind": "functional_vector", "polarity": "positive",
     "stimulus": "shift a bit through", "expected": "bit appears at q"}]}


def _staged_project(tmp_path: Path, rtl: str) -> Path:
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps(L10))
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "shift_top.v").write_text(rtl)
    return project


# --------------------------------------------------------------------------
# N2 — instance recognition
# --------------------------------------------------------------------------
def test_unit_tb_binds_the_root_when_its_child_is_an_instance_array(tmp_path):
    """RED on main: 2 candidates ['cell_stage', 'shift_top'], nothing emitted."""
    project = _staged_project(tmp_path, ARRAY_TOP)
    mod, ports, why = TBG.resolve_dut(project, "chip_top")
    assert mod == "shift_top", why
    assert [p[2] for p in ports] == ["clk", "rst", "d", "w", "q"]
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "chip_top", report=report) == 1, report
    tb = project / "phase2" / "stage1" / "sim" / "tb" / "tc_shift.v"
    assert "shift_top u_dut" in tb.read_text()


def test_instance_shapes_are_all_seen_as_instantiations(tmp_path):
    """Each child below is instantiated exactly one way; any shape the regex
    cannot see leaves that child as an extra root."""
    rtl = """\
module top_m (input clk, input a, output y);
  wire [3:0] t;
  generate
    for (genvar g = 0; g < 2; g = g + 1) begin : blk leaf_gen u_g (.a(a), .y(t[g]));
    end
  endgenerate
  generate if (1) begin leaf_if u_if (.a(a), .y(t[2])); end
  else leaf_else u_else (.a(a), .y(t[2]));
  endgenerate
  leaf_param #(.W((2)), .D(1)) u_p [1:0] (.a({a, a}), .y(t[1:0]));
  leaf_plain u_x (.a(a), .y(t[3])); leaf_same_line u_y (.a(a), .y(y));
endmodule
"""
    for leaf in ("leaf_gen", "leaf_if", "leaf_else", "leaf_param",
                 "leaf_plain", "leaf_same_line"):
        rtl += f"module {leaf} (input a, output y); assign y = a; endmodule\n"
    project = _staged_project(tmp_path, rtl)
    mod, _ports, why = TBG.resolve_dut(project, "not_a_module")
    assert mod == "top_m", why


def test_runner_graph_root_sees_an_instance_array(tmp_path):
    """The runner's own root search (clause (c)) had the same blind spot."""
    import design_one_shot_runner as R
    project = _staged_project(tmp_path, ARRAY_TOP)
    assert R._v661_resolve_dut_module(project, "chip_top", None) == "shift_top"


# --------------------------------------------------------------------------
# N2 — the top handed to phase 2 when the RTL is still under input/
# --------------------------------------------------------------------------
def _supplied_project(tmp_path: Path) -> Path:
    project = tmp_path / "sup"
    vend = project / "input" / "vendor_rtl"
    vend.mkdir(parents=True)
    (vend / "shift_top.v").write_text(ARRAY_TOP)
    return project






# Review wave 4c: the header mask read comments, crossed newlines and left a
# bare `module` keyword the instance search took for an instance name. Each
# shape below is {file name: text}; the expected top is the design's only root.
_LEAF = "module {n} (input a, output y); assign y = a; endmodule\n"














# --------------------------------------------------------------------------
# N3 — the declaration on the supplied-RTL path
# --------------------------------------------------------------------------
CONTRACT = """# L7 — verification plan

The Plugin MUST declare `{path}` before authoring:

| Field | Required | Example |
|---|---|---|
| `shift_direction` | Yes | `"left"` / `"right"` |
| `reset_style` | Yes | `"sync"` / `"async"` |
""".format(path=DECL_PATH)


def _consumed_project(tmp_path: Path, supplied: bool = True) -> Path:
    """The state phase 2's consume step leaves: input file, staged copy and
    SOURCE_MANIFEST. `supplied=False` is the same tree with no manifest."""
    project = _supplied_project(tmp_path)
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(CONTRACT)
    if supplied:
        import reused_ip_rtl_consume as C
        res = C.consume_reused_ip_rtl(project)
        assert res["reused_ip"] is True, res
    return project


def _emit(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(EMITTER), str(project), *args],
                          capture_output=True, text=True, timeout=120)


def test_supplied_rtl_declaration_is_written_with_provenance(tmp_path):
    """RED on main: rc 1 and no file at all. Run exactly as the pre-fix CLI
    accepts, so main answers rather than refusing the arguments."""
    project = _consumed_project(tmp_path)
    cp = _emit(project)
    # The required free choices are still undeclared: the refusal stands.
    assert cp.returncode == 1, cp.stderr
    assert (project / DECL_PATH).is_file(), cp.stderr
    decl = json.loads((project / DECL_PATH).read_text())
    assert set(decl) == {"supplied_rtl"}, decl
    rec = decl["supplied_rtl"]
    assert rec["source"] == "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    [f] = rec["files"]
    assert f["input"] == "input/vendor_rtl/shift_top.v"
    assert f["staged"] == "phase2/stage1/rtl/shift_top.v"
    assert f["byte_identical"] is True and len(f["input_sha256"]) == 64
    # No top was handed over, and the record says so rather than guessing.
    assert rec["top"]["value"] is None
    assert rec["top"]["status"] == "NOT_DETERMINED"
    assert "ports" not in rec


def test_the_record_carries_the_top_and_its_ports(tmp_path):
    project = _consumed_project(tmp_path)
    cp = _emit(project, "--supplied-top", "shift_top")
    assert cp.returncode == 1, cp.stderr
    rec = json.loads((project / DECL_PATH).read_text())["supplied_rtl"]
    assert rec["top"]["value"] == "shift_top"
    assert rec["top"]["defined_in"] == "phase2/stage1/rtl/shift_top.v"
    assert [(p["direction"], p["name"]) for p in rec["ports"]["value"]] == [
        ("input", "clk"), ("input", "rst"), ("input", "d"), ("input", "w"),
        ("output", "q")]
    assert [p["width"] for p in rec["ports"]["value"]][3] == "[n-1:0]"
    assert "shift_top" in rec["ports"]["source"]


def test_gate_names_the_undeclared_choices_not_an_absent_file(tmp_path):
    """The record declares no free choice, so the gate stays red — for the
    reason that is true. RED on main: FAIL_ABSENT."""
    import spec_required_artifact_check as G
    import spec_declaration_emit as SDE
    project = _consumed_project(tmp_path)
    _emit(project)
    contract, _why, _p = SDE.select_contract(project, None, [])
    rep = SDE.verify_declaration(project, contract, project / DECL_PATH)
    assert rep["verdict"] != "FAIL_ABSENT"
    assert sorted(rep["missing_required"]) == ["reset_style",
                                               "shift_direction"]
    G._SUBSTANCE_CONTRACT_CACHE.clear()
    status, _reason, source = G._substance_of(project, DECL_PATH,
                                              project / DECL_PATH)
    assert (status, source) == ("FAIL_UNSATISFIED", "CONTRACT")


def test_no_supplied_rtl_means_no_file_as_before(tmp_path):
    """Control, GREEN on main too: without the consume manifest the
    fail-closed contract is unchanged — rc 1 and nothing written."""
    project = _consumed_project(tmp_path, supplied=False)
    cp = _emit(project)
    assert cp.returncode == 1
    assert not (project / DECL_PATH).exists()


def test_declared_choices_and_the_record_coexist(tmp_path):
    """When the author declares the choices, the emit path keeps the record
    beside them and the verify passes. RED on main: no record."""
    import spec_declaration_emit as SDE
    project = _consumed_project(tmp_path)
    cp = _emit(project, "--set", "shift_direction=left",
               "--set", "reset_style=async")
    assert cp.returncode == 0, cp.stderr
    decl = json.loads((project / DECL_PATH).read_text())
    assert decl["shift_direction"] == "left"
    assert decl["supplied_rtl"]["files"][0]["byte_identical"] is True
    contract, _why, _p = SDE.select_contract(project, None, [])
    rep = SDE.verify_declaration(project, contract, project / DECL_PATH)
    assert rep["verdict"] == "PASS", rep


def test_runner_step_writes_the_record_with_the_resolved_top(tmp_path):
    """The phase-2 step resolves the top against the staged modules and hands
    it over; its call site passes no top, and `--top-name` is `chip_top` by
    default, which this design does not have. RED on main: no file."""
    import design_one_shot_runner as R
    project = _consumed_project(tmp_path)
    res = R.step_arith_declaration_emit(project)
    assert res.status == "NOT_MEASURED"
    assert (project / DECL_PATH).is_file(), res.detail
    assert "wrote only the supplied-RTL record" in res.detail, res.detail
    decl = json.loads((project / DECL_PATH).read_text())
    assert decl["supplied_rtl"]["top"]["value"] == "shift_top"


def test_the_record_is_not_read_as_a_feature_decision(tmp_path):
    """A supplied port called `m` is not a decision to implement feature M."""
    import l10_tb_conformance_check as L10C
    project = tmp_path / "p"
    (project / "plugin_output").mkdir(parents=True)
    (project / DECL_PATH).write_text(json.dumps({"supplied_rtl": {
        "ports": {"value": [{"direction": "input", "width": "", "name": "m"}]}
    }}))
    assert L10C.conditional_feature_declared(str(project), "M") is False
    (project / DECL_PATH).write_text(json.dumps({"isa_extensions": ["M"]}))
    assert L10C.conditional_feature_declared(str(project), "M") is True


# --------------------------------------------------------------------------
# Review wave 4c, MINORs: report what the emitter DID; never cost an author
# their file; record what is in rtl/ now.
# --------------------------------------------------------------------------
def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_step_does_not_claim_a_pre_existing_file_as_the_record(tmp_path):
    """No supplied RTL, a declaration another writer left: the step must not
    say it wrote the record, nor list that file as its artefact."""
    import design_one_shot_runner as R
    project = _consumed_project(tmp_path, supplied=False)
    decl = project / DECL_PATH
    decl.parent.mkdir(parents=True)
    decl.write_text(json.dumps({"ip_catalog_used": []}))
    before = _sha(decl)
    res = R.step_arith_declaration_emit(project)
    assert _sha(decl) == before
    assert "supplied-RTL record" not in res.detail, res.detail
    assert "left untouched" in res.detail, res.detail
    assert res.output_files == []


def test_step_reports_the_path_the_contract_names(tmp_path):
    """The record is written where the SPEC's clause points; the step names
    that file, not an assumed plugin_output/declaration.json."""
    import design_one_shot_runner as R
    project = _consumed_project(tmp_path)
    other = "plugin_output/impl_choices.json"
    (project / "input" / "docs" / "L7_verification_plan.md").write_text(
        CONTRACT.replace(DECL_PATH, other))
    res = R.step_arith_declaration_emit(project)
    assert (project / other).is_file()
    assert not (project / DECL_PATH).exists()
    assert str(project / other) in res.detail, res.detail
    assert res.output_files == [str(project / other)]


def test_fail_closed_leaves_an_unreadable_author_file_alone(tmp_path):
    """One stray comma in the author's file must not be answered by replacing
    the file with the record alone."""
    project = _consumed_project(tmp_path)
    decl = project / DECL_PATH
    decl.parent.mkdir(parents=True)
    decl.write_text('{"shift_direction": "left", "reset_style": "async",}\n')
    before = _sha(decl)
    cp = _emit(project, "--supplied-top", "shift_top")
    assert cp.returncode == 1, cp.stderr
    assert _sha(decl) == before
    assert "left untouched" in cp.stderr, cp.stderr


def test_a_file_the_cone_pruned_is_recorded_as_pruned_not_modified(tmp_path):
    """The real cone reduction moves an orphan out of rtl/. The record must say
    so; `byte_identical: false` would claim the flow changed supplied RTL."""
    import reused_ip_rtl_consume as C
    import rtl_transitive_cone as CONE
    project = _supplied_project(tmp_path)
    (project / "input" / "vendor_rtl" / "orphan.v").write_text(
        "module orphan (input a, output y); assign y = a; endmodule\n")
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(CONTRACT)
    assert C.consume_reused_ip_rtl(project)["reused_ip"] is True
    rtl = project / "phase2" / "stage1" / "rtl"
    cr = CONE.transitive_cone("shift_top", rtl)
    assert CONE.prune_to_cone(rtl, cr) == ["orphan.v"]
    _emit(project, "--supplied-top", "shift_top")
    files = {f["input"]: f for f in json.loads(
        (project / DECL_PATH).read_text())["supplied_rtl"]["files"]}
    kept = files["input/vendor_rtl/shift_top.v"]
    gone = files["input/vendor_rtl/orphan.v"]
    assert (kept["status"], kept["byte_identical"]) == ("staged", True)
    assert (gone["status"], gone["byte_identical"]) == ("pruned_out_of_cone",
                                                        None)
    assert gone["source"].endswith(CONE.RESTORE_MANIFEST_NAME)
