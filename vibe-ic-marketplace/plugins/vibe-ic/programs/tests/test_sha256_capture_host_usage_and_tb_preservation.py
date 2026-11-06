#!/usr/bin/env python3
"""sha256 x sky130A acceptance capture (2026-09-02, v1.15.33 → v1.15.44).

Four chip-AGNOSTIC defects measured on one real acceptance run, each pinned
here with the shape that failed and the shape that must hold:

  1. README usage sequences reached L12 as bare prose with no category, so
     `l12_sequences_in_consumed_layer_check` refused (UNTYPED_STEPS) and
     `l12_sequence_implementation_check` refused (NO_IMPL_MODULE) for a
     host-side procedure that no module could ever be named after.
  2. `testbench_gen.emit_unit_tb` regenerated the substance-floor scaffold
     over a testbench whose author had followed the scaffold's own
     instruction (write the oracle, delete the marker) — every runner
     invocation erased the authored oracle.
  3. `step_professional_tb_gen` declared "iverilog/cocotb not reachable in
     the configured container" — and invalidated a green results.xml — while
     the runner was executing INSIDE the container with iverilog, vvp, make
     and cocotb all on its own PATH.

Every fixture is synthetic; no chip, vendor or design-name literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import readme_usage_sequence_extractor as RUSE          # noqa: E402
import testbench_gen as TBG                              # noqa: E402


README = (
    "## One full operation (SW perspective)\n"
    "\n"
    "```\n"
    "1. (optional) read ADDR_ID0/1/VERSION to confirm chip identity\n"
    "2. write ADDR_DATA0..15 = 512-bit padded input block\n"
    "3. write ADDR_CTRL bit2 = MODE (1=long, 0=short)\n"
    "4. poll ADDR_STATUS until bit0 (READY) = 1  // ~66 clk cycles\n"
    "5. (optional) check bit1 (VALID) = 1\n"
    "6. read ADDR_OUT0..7 = 256-bit result\n"
    "7. for multi-block: repeat 2-6 with NEXT instead of INIT\n"
    "```\n"
)


# ---------------------------------------------------------------------------
# 1. README usage sequences: category + typed steps
# ---------------------------------------------------------------------------
def test_readme_sequences_are_categorised_and_typed():
    seqs = RUSE.extract_usage_sequence_from_readme(README)
    assert seqs, "the canonical numbered host procedure must still be picked"
    for seq in seqs:
        assert seq["category"] == RUSE.HOST_USAGE_CATEGORY
        assert seq["trigger"] == "host_initiates"


def test_type_step_action_shapes():
    w = RUSE.type_step_action("write ADDR_CTRL bit2 = MODE (1=long, 0=short)")
    assert w["action_type"] == "write" and w["target"] == "ADDR_CTRL"
    assert w["expected_signal"].startswith("ADDR_CTRL bit2 = MODE")
    p = RUSE.type_step_action(
        "poll ADDR_STATUS until bit0 (READY) = 1  // ~66 clk cycles")
    assert p["action_type"] == "poll" and p["latency_cycles"] == 66
    assert p["wait_for"] == "ADDR_STATUS until bit0 (READY) = 1"
    c = RUSE.type_step_action("(optional) check bit1 (VALID) = 1")
    assert c["optional"] is True and c["check"] == "bit1 (VALID) = 1"
    r = RUSE.type_step_action("read ADDR_OUT0..7 = 256-bit result")
    assert r["action_type"] == "read" and r["expected_response"] == "256-bit result"
    rp = RUSE.type_step_action("for multi-block: repeat 2-6 with NEXT instead of INIT")
    assert rp["next_state"] == "step 2" and rp["condition"] == "multi-block"
    # prose stays prose — no invented detail
    assert RUSE.type_step_action("The block is then processed internally") == {}


# ---------------------------------------------------------------------------
# 2. emit_unit_tb never clobbers an authored oracle
# ---------------------------------------------------------------------------
GOOD_DUT = """\
module widget_core (
    input        clk,
    input        reset_n,
    input  [7:0] data_in,
    output reg [7:0] data_out,
    output reg       valid
);
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin data_out <= 8'd0; valid <= 1'b0; end
    else begin data_out <= data_in; valid <= 1'b1; end
  end
endmodule
"""

L10 = {"test_cases": [
    {"name": "vec_alpha", "kind": "functional_vector",
     "stimulus": "0x11", "expected": "0x11"},
]}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps(L10))
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "widget_core.v").write_text(GOOD_DUT)
    return project


def test_authored_unit_tb_is_preserved_across_regeneration(tmp_path):
    project = _project(tmp_path)
    tb_dir = project / "phase2" / "stage1" / "sim" / "tb"
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "widget_core", report=report) == 1
    tb = tb_dir / "vec_alpha.v"
    scaffold = tb.read_text()
    assert TBG.ORACLE_NONE_MARKER in scaffold
    # the author follows the scaffold's instruction: real oracle, marker gone
    authored = scaffold.replace(f"// {TBG.ORACLE_NONE_MARKER}\n", "").replace(
        "#1000;", "#1000; if (u_dut.data_out !== 8'h11) errors = errors + 1;")
    assert TBG.ORACLE_NONE_MARKER not in authored
    tb.write_text(authored)
    report2: dict = {}
    assert TBG.emit_unit_tbs(project, "widget_core", report=report2) == 1
    assert tb.read_text() == authored, "regeneration erased the authored oracle"
    assert report2["preserved_authored"][0]["case"] == "vec_alpha"


def test_scaffold_still_carrying_the_marker_is_refreshed(tmp_path):
    project = _project(tmp_path)
    tb = project / "phase2" / "stage1" / "sim" / "tb" / "vec_alpha.v"
    assert TBG.emit_unit_tbs(project, "widget_core") == 1
    stale = tb.read_text() + "\n// stale trailing edit\n"
    tb.write_text(stale)
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "widget_core", report=report) == 1
    assert "stale trailing edit" not in tb.read_text()
    assert "preserved_authored" not in report


# ---------------------------------------------------------------------------
# 3. professional TB runs where the toolchain actually is
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. step 0.5ic: the run's own producer records are run evidence, on every pass
# ---------------------------------------------------------------------------
import submission_template_check as STC                 # noqa: E402


def _doc(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


def test_checks_carry_the_producer_stamp_forward(tmp_path):
    gen = _doc(tmp_path, "td.json", {"program": "tapeout_declaration_gen",
                                     "emitted_by": "tapeout_declaration_gen v9"})
    # a prior audit's document keeps the record it already carries
    # the gate's own bare document (nothing to carry) yields nothing
    assert STC._producer_record_of({"program": "submission_template_ingest",
                                    "ingest": {}}) == {"program": "submission_template_ingest"}
    assert STC._producer_record_of({"schema": "x", "ingest": {}}) is None
    assert STC._producer_record_of({"program": STC.PROGRAM}) is None


# ---------------------------------------------------------------------------
# 5. non-protocol / macro-less designs: gates disclose the design-declared N/A
# ---------------------------------------------------------------------------
import l21_macro_supply_rail_declared_check as L21          # noqa: E402
import _flow_reason_taxonomy as TAX                          # noqa: E402


def _l3(project: Path, opcodes: list) -> Path:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol", "opcodes": opcodes,
        "no_opcodes_in_input": not opcodes}))
    return gd


def test_state_transition_gate_discloses_no_protocol_as_design_na(tmp_path, capsys):
    project = tmp_path / "proj"
    _l3(project, [])
    tb = project / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "t.v").write_text("module t; endmodule\n")
    cov = project / "reports" / "phase2" / "coverage" / "coverage_actual.json"
    cov.parent.mkdir(parents=True)
    cov.write_text(json.dumps({"verdict": "PASS", "vectors_total": 3}))  # functional payload, no entries
    out_json = tmp_path / "fstc.json"
    captured = capsys.readouterr()
    assert "VACUOUS_PASS" in captured.out and "no command protocol" in captured.out
    rep = json.loads(out_json.read_text())
    assert rep["reason_class"] == "DESIGN_DECLARED_NA"
    assert TAX.infer_nonverdict_reason(verdict="NOT_MEASURED",
                                       message=captured.out) == TAX.DESIGN_DECLARED_NA


def test_behavioural_evidence_skip_is_read_as_design_declared(tmp_path, capsys):
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"ports": ["clk"]}))
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    assert line.startswith("SKIPPED-CONDITION")
    assert TAX.infer_nonverdict_reason(verdict="NOT_APPLICABLE",
                                       message=line) == TAX.DESIGN_DECLARED_NA


def test_l21_no_macro_lef_skip_carries_reason_class(tmp_path, capsys):
    project = tmp_path / "proj"
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    (project / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text("{}")
    out = tmp_path / "l21.json"
    rc = L21.main([str(project), "--json", str(out)])
    captured = capsys.readouterr()
    assert rc == 2, captured.out + captured.err
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "SKIP"
    assert rep["reason_class"] == "DESIGN_DECLARED_NA"
    line = [l for l in captured.out.splitlines() if l.startswith("[SKIP]")][-1]
    assert TAX.infer_nonverdict_reason(verdict="SKIP", message=line) == TAX.DESIGN_DECLARED_NA


# ---------------------------------------------------------------------------
# 6. step 2 on a self-tape-out, non-protocol, non-git project
# ---------------------------------------------------------------------------
import slot_pad_budget_check as SPB                         # noqa: E402


def test_slot_pad_budget_reads_the_declared_self_tapeout_route(tmp_path, capsys):
    project = tmp_path / "proj"
    st = project / "input" / "submission_template"
    st.mkdir(parents=True)
    (st / "SELF_TAPEOUT.txt").write_text("# tapeout_declaration: self tape-out, no operator\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text("module top(input wire clk, output wire q); assign q = clk; endmodule\n")
    out = project / "spb.json"
    rc = SPB.main([str(project), "--top", "top", "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 2 and rep["verdict"] == "NOT_APPLICABLE"
    assert rep["reason_class"] == TAX.DESIGN_DECLARED_NA
    assert "SELF_TAPEOUT.txt" in rep["reason"]
    # without any router file the old answer stands: step 0.5ic has not run
    (st / "SELF_TAPEOUT.txt").unlink()
    rc = SPB.main([str(project), "--top", "top", "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 2 and rep["verdict"] == "UNDECIDED"
    assert rep["reason_class"] == TAX.BLOCKED_BY_UPSTREAM


def test_bug_density_metric_names_the_missing_instrument(tmp_path, capsys, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "[skipped]" in l][-1]
    assert TAX.infer_nonverdict_reason(verdict="NOT_MEASURED", message=line) == TAX.CAPABILITY_ABSENT


# ---------------------------------------------------------------------------
# 7. the PDK tree survives the via-legalized tech-LEF substitution
# ---------------------------------------------------------------------------
def test_pdk_dir_resolves_from_the_distribution_source_after_substitution(tmp_path):
    import phase3_one_shot_runner as P3
    dist = "/pdks/somepdk/libs.ref/some_lib/techlef/some_lib__nom.tlef"
    derived = str(tmp_path / "phase3" / "stage3" / "pnr" / "active_via_legalized.tlef")
    pdk = P3.PdkConfig(name="somepdk", liberty="x.lib", tech_lef=dist,
                       cell_lef="c.lef", cell_gds=None, site="s", drc_deck=None)
    assert P3._pdk_dir_of(pdk) == "/pdks/somepdk"
    # the remediation substitutes the derived copy and records its source
    pdk.tech_lef_source = dist
    pdk.tech_lef = derived
    assert P3._pdk_dir_of(pdk) == "/pdks/somepdk"
    # with no recorded source the derived copy alone cannot name a tree
    pdk.tech_lef_source = None
    assert P3._pdk_dir_of(pdk) == ""
