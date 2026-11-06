"""U18 — Step 38: an OPEN item owned by this flow blocks the hand-off gate, and
the flow closes its own item by converting the Step-5 traces into ATE patterns.

THE DEFECT (IC_BLOCKER_AUDIT 2026-09-29, U18; evidence cx_spmic2_run)
====================================================================
`reports/phase3/foundry_handoff_check.json` of the only spm tail run says
verdict PASS while its own `handoff_open_items` lists

    corner_test_vectors.json  PENDING_FOUNDRY_test_patterns  owner=this_flow  OPEN

"conversion of the L10 seeds already listed in this member into ATE patterns
from the cocotb / Verilator traces this flow produced". The foundry, the
operator, the test house and the contract close their items outside this flow;
`this_flow` is us, and a kit that still owes our own deliverable is not
complete. No flow step converted anything: Step 5 wrote no trace at all.

THE RULE NOW
============
* `foundry_handoff_package_check`: a `this_flow` item recorded OPEN is an ERROR
  (FOUNDRY_HANDOFF_THIS_FLOW_ITEM_OPEN). A `this_flow` item recorded CLOSED
  stands only on the files it names, re-hashed, each naming a source trace
  that still hashes to its record (…_CLOSED_WITHOUT_EVIDENCE otherwise).
* `full_stack_functional_tb` (Step 5) dumps each case's DUT scope (depth 1) to
  a VCD through a second simulation top and records it with its sha256.
* `ate_pattern_gen` converts every seed Step 5 PASSED into an event-timed
  pattern; `foundry_handoff_pack_gen` closes the item only when every seed Step
  5 counted as a functional case has one.
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))

import ate_pattern_gen as ATE  # noqa: E402
import foundry_handoff_pack_gen as FH  # noqa: E402
import full_stack_functional_tb as FSF  # noqa: E402
import _step5_trace_fixture as S5  # noqa: E402

CHECKER = PROGRAMS / "foundry_handoff_package_check.py"
REAL_KIT_MEMBER = (HERE / "fixtures" / "u18_step38"
                   / "cx_spmic2_run.corner_test_vectors.json")
_GDS_BOUNDARY_RECORD = b"\x00\x04\x08\x00"
OPEN_RULE = "FOUNDRY_HANDOFF_THIS_FLOW_ITEM_OPEN"
CLOSED_RULE = "FOUNDRY_HANDOFF_THIS_FLOW_CLOSED_WITHOUT_EVIDENCE"


def _gate(proj):
    out = proj / "gate.json"
    rc = subprocess.run(
        [sys.executable, str(CHECKER), str(proj), "--json", str(out)],
        capture_output=True, text=True).returncode
    rep = json.loads(out.read_text())
    return rc, rep, {f["rule"] for f in rep["findings"]}


def _project(tmp_path):
    """A complete-but-for-patterns kit: the same shape the owner-taxonomy
    tests use, with a chip GDS that carries geometry and an admission gate."""
    p = tmp_path / "alpha"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/chip_top.sv").write_text(
        "module chip_top(input clk);\nendmodule\n")
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase2/stage2/synth/netlist.v").write_text(
        "module top(input clk);\n  buf_cell _0_ (.A(clk), .X());\nendmodule\n")
    (p / "phase3/stage3/pnr").mkdir(parents=True)
    (p / "phase3/stage3/pnr/pnr.tcl").write_text(
        "read_liberty /foss/pdks/examplepdk/examplepdk_sc__tt_025C_1v80.lib\n"
        "link_design chip_top\n")
    (p / "phase3/stage4/gds").mkdir(parents=True)
    (p / "phase3/stage4/gds/alpha.gds").write_bytes(
        _GDS_BOUNDARY_RECORD + b"\x00\x06\x00\x02alph")
    (p / "phase1/generated_docs").mkdir(parents=True)
    (p / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "alpha"}))
    gate = p / "reports/phase3/prestream_gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": "a" * 64}))
    pnr = p / "phase3/stage3/pnr"
    stream = pnr / "alpha.gds"
    stream.write_bytes((p / "phase3/stage4/gds/alpha.gds").read_bytes())
    basis = []
    for filename in ("routed.def", "constraint.sdc"):
        path = pnr / filename
        path.write_text("synthetic layout input\n")
        basis.append(path)
    return p


# ── the RED: the real run's kit, the gate said PASS ────────────────────────

def test_the_real_run_kit_member_with_our_open_item_is_refused(tmp_path):
    """cx_spmic2_run's own corner_test_vectors.json, dropped into an otherwise
    complete kit. On main the gate returned rc 0 PASS over it."""
    proj = _project(tmp_path)
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/corner_test_vectors.json"
    real = json.loads(REAL_KIT_MEMBER.read_text())
    # The real member's identity (design, top, pdk, mode) describes its own
    # run; this fixture's are taken instead so that the ONLY thing the real
    # member brings is its open-item list — the pdk/mode rules are not what
    # this test is about, and on main the gate then answers rc 0 PASS.
    gen = json.loads(member.read_text())
    for key in ("design_identity", "design_top", "pdk", "handoff_mode"):
        real[key] = gen[key]
    member.write_text(json.dumps(real, indent=2))
    items = {i["field"]: i for i in real["open_items"]}
    assert items["PENDING_FOUNDRY_test_patterns"]["owner"] == "this_flow"
    assert items["PENDING_FOUNDRY_test_patterns"]["status"] == "OPEN"
    rc, rep, rules = _gate(proj)
    assert OPEN_RULE in rules, rep
    assert rc == 1 and rep["verdict"] == "FAIL"


def test_a_generated_kit_with_no_trace_keeps_our_item_open_and_fails(tmp_path):
    proj = _project(tmp_path)
    FH.main([str(proj)])
    kit = json.loads((proj / "phase3/stage4/foundry_handoff/"
                      "corner_test_vectors.json").read_text())
    item = {i["field"]: i for i in kit["open_items"]}[
        "PENDING_FOUNDRY_test_patterns"]
    assert item["status"] == "OPEN"
    assert "PENDING_FOUNDRY_test_patterns" in kit
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and OPEN_RULE in rules


def test_other_parties_open_items_do_not_block(tmp_path):
    """Negative control: the loadboard (test house), the mask layers (foundry)
    stay OPEN in the passing kit below — only OUR item blocks."""
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    rc, rep, rules = _gate(proj)
    assert rc == 0, rep
    owners_open = {i["owner"] for i in rep["handoff_open_items"]
                   if i["status"] == "OPEN"}
    assert "this_flow" not in owners_open
    assert {"test_house", "foundry"} <= owners_open


# ── the conversion: real trace in, patterns out, item closed ───────────────

def test_the_step5_trace_is_converted_and_closes_the_item(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    kdir = proj / "phase3/stage4/foundry_handoff"
    kit = json.loads((kdir / "corner_test_vectors.json").read_text())
    item = {i["field"]: i for i in kit["open_items"]}[
        "PENDING_FOUNDRY_test_patterns"]
    assert item["status"] == FH.STATUS_CLOSED
    assert "PENDING_FOUNDRY_test_patterns" not in kit
    assert [p["case"] for p in kit["ate_patterns"]] == [S5.CASE]
    head = json.loads((kdir / "ate_patterns" / f"{S5.CASE}.json").read_text())
    assert [c["name"] for c in head["columns"]["drive"]] == \
        ["clk", "rst", "x", "y"]
    assert [c["name"] for c in head["columns"]["expect"]] == ["p"]
    assert head["columns"]["drive"][2]["width"] == 32
    rows = gzip.decompress((kdir / "ate_patterns" / f"{S5.CASE}.vec.gz")
                           .read_bytes()).decode().splitlines()
    assert len(rows) == head["vector_count"]
    # Read off the real iverilog VCD: at 0 ps rst=1, clk=0, output undefined;
    # the pad-ring output settles 2 ns after the first rising clock edge.
    assert rows[0] == "0 0_1_" + "0" * 32 + "_0 x 1_0"
    assert rows[1].startswith("5000 1_1_") and rows[1].split()[2] == "x"
    assert rows[2].startswith("7000 1_1_") and rows[2].split()[2] == "0"
    rc, rep, rules = _gate(proj)
    assert rc == 0, rep
    assert OPEN_RULE not in rules and CLOSED_RULE not in rules


def test_the_same_trace_gives_the_same_pattern_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        S5.plant(d)
        ATE.emit(d, d / "out", [S5.CASE])
    assert (a / "out" / f"{S5.CASE}.vec.gz").read_bytes() == \
        (b / "out" / f"{S5.CASE}.vec.gz").read_bytes()


def test_a_case_step5_did_not_pass_is_not_converted(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj, state="failed")
    FH.main([str(proj)])
    kit = json.loads((proj / "phase3/stage4/foundry_handoff/"
                      "corner_test_vectors.json").read_text())
    assert kit["ate_patterns"] == []
    assert kit["ate_patterns_not_converted"][0]["case"] == S5.CASE
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and OPEN_RULE in rules


def test_a_seed_without_a_step5_row_keeps_the_item_open(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj)
    l10 = proj / "phase1/generated_docs/L10_TEST_CASES.json"
    d = json.loads(l10.read_text())
    d["test_cases"].append({"id": "a_second_case"})
    l10.write_text(json.dumps(d))
    FH.main([str(proj)])
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and OPEN_RULE in rules


def test_a_trace_that_no_longer_matches_step5_is_not_converted(tmp_path):
    proj = _project(tmp_path)
    rec = S5.plant(proj)
    vcd = proj / rec["cases"][0]["trace"]["vcd"]
    vcd.write_text(vcd.read_text() + "#999999\n1o\n")
    res = ATE.emit(proj, tmp_path / "out", [S5.CASE])
    assert res["patterns"] == []
    assert "no longer hashes" in res["not_converted"][0]["reason"]


# ── a status word alone closes nothing ─────────────────────────────────────

def test_a_hand_written_closed_status_without_evidence_fails(tmp_path):
    proj = _project(tmp_path)
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/corner_test_vectors.json"
    kit = json.loads(member.read_text())
    kit.pop("PENDING_FOUNDRY_test_patterns")
    for it in kit["open_items"]:
        if it["field"] == "PENDING_FOUNDRY_test_patterns":
            it["status"] = "CLOSED"
    member.write_text(json.dumps(kit, indent=2))
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules


def test_a_pattern_whose_source_trace_changed_after_closing_fails(tmp_path):
    proj = _project(tmp_path)
    rec = S5.plant(proj)
    FH.main([str(proj)])
    assert _gate(proj)[0] == 0
    vcd = proj / rec["cases"][0]["trace"]["vcd"]
    vcd.write_text(vcd.read_text() + "#999999\n1o\n")
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules


def test_an_edited_pattern_file_fails(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    head = proj / "phase3/stage4/foundry_handoff/ate_patterns" \
        / f"{S5.CASE}.json"
    d = json.loads(head.read_text())
    d["vector_count"] += 1
    head.write_text(json.dumps(d))
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules


# ── Step 5 writes the trace ────────────────────────────────────────────────

def test_step5_dumper_targets_the_single_dut_instance(tmp_path):
    tb = ("module case_3;\n  reg clk;\n  // chip_top ghost (.clk(clk));\n"
          "  chip_top dut (.clk(clk));\nendmodule\n")
    assert FSF.dut_instance_name(tb, "chip_top") == "dut"
    src, trace = FSF.trace_dumper(tb, "case_3", "chip_top", tmp_path)
    assert trace["scope"] == "case_3/dut"
    text = src.read_text()
    assert f"module {FSF.TRACE_TOP};" in text
    assert "$dumpvars(1, case_3.dut);" in text
    assert '$dumpfile("case_3.vcd");' in text
    two = tb + "module x; chip_top a (.clk()); chip_top b (.clk()); endmodule\n"
    src2, trace2 = FSF.trace_dumper(two, "case_3", "chip_top", tmp_path)
    assert src2 is None and trace2["vcd"] is None


def test_step5_records_the_real_trace_with_its_scope_and_hash(tmp_path):
    vcd = tmp_path / "case_3.vcd"
    vcd.write_bytes(S5.trace_bytes())
    rec = FSF.record_trace(tmp_path, {"vcd": vcd, "scope": "case_3/dut",
                                      "dut_module": "chip_top"})
    assert rec["scope_verified"] is True
    assert rec["sha256"] == S5.sha256(vcd)
    bad = FSF.record_trace(tmp_path, {"vcd": vcd, "scope": "case_3/nope",
                                      "dut_module": "chip_top"})
    assert bad["scope_verified"] is False


def test_step5_generate_builds_with_the_trace_top(tmp_path, monkeypatch):
    """Drive `generate` with a dispatch that records argv: the case build names
    the trace top as a second `-s` root and compiles the dumper."""
    seen = []

    def disp(argv, run_dir, container, tool, timeout):
        seen.append(list(argv))
        return 1, "stub: no simulator"

    import testbench_gen as TBG

    def emit(project, core, kind, report, out_dir=None, scaffold=True,
             case_stated=False):
        (Path(out_dir) / "c1.v").write_text(
            "module c1;\n  reg clk;\n  core dut (.clk(clk));\nendmodule\n")
        return 1

    monkeypatch.setattr(TBG, "emit_unit_tbs", emit)
    monkeypatch.setattr(TBG, "load_l10_cases",
                        lambda p: [{"id": "c1", "name": "c1"}])
    monkeypatch.setattr(TBG, "resolve_dut",
                        lambda p, c: ("core", [("input", "", "clk")], ""))
    monkeypatch.setattr(FSF, "required_full_stack_top", lambda p, r=None: {
        "pad_ring": False, "module": "core", "core_module": "core",
        "refusal": None})
    monkeypatch.setattr(TBG, "_detect_ic_class", lambda p: None)
    rec = FSF.generate(tmp_path, None, None, dispatch=disp)
    build = [a for a in seen if a and a[0] == FSF.SIMULATOR][0]
    assert build[build.index("-s", build.index("-s") + 1) + 1] == FSF.TRACE_TOP
    assert build[-2].endswith(f"{FSF.TRACE_TOP}.v")
    assert build[-1].endswith("c1.v")       # the case testbench stays last
    assert rec["dut_ports"] == [{"name": "clk", "direction": "input"}]


# ── round 2: a large member is parsed in full; the vectors are re-hashed ────

def test_an_open_item_in_a_member_longer_than_the_todo_slice_still_fails(
        tmp_path):
    """r2 MAJOR 1. The gate parsed `read_text()[:20000]`; a member longer than
    that became a silent non-dict and every rule on it switched off. 120 L10
    seeds and no Step-5 record put corner_test_vectors.json far past the slice
    (each unconverted seed carries its reason) with our item still OPEN."""
    proj = _project(tmp_path)
    l10 = proj / "phase1/generated_docs/L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": [
        {"id": f"case_{i:03d}"} for i in range(120)]}))
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/corner_test_vectors.json"
    assert len(member.read_text()) > 20000
    item = {i["field"]: i for i in json.loads(member.read_text())[
        "open_items"]}["PENDING_FOUNDRY_test_patterns"]
    assert item["status"] == "OPEN"
    rc, _rep, rules = _gate(proj)
    assert OPEN_RULE in rules
    assert rc == 1


def test_a_member_that_is_not_json_is_refused_by_name(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/corner_test_vectors.json"
    member.write_text(member.read_text()[:-40])
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and "FOUNDRY_HANDOFF_MEMBER_UNPARSEABLE" in rules


def test_an_altered_vector_file_fails(tmp_path):
    """r2 MAJOR 2. The .vec.gz is the pattern a tester loads; the header only
    describes it. Fabricated rows (header untouched) must not stay CLOSED."""
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    assert _gate(proj)[0] == 0
    vec = proj / "phase3/stage4/foundry_handoff/ate_patterns" \
        / f"{S5.CASE}.vec.gz"
    vec.write_bytes(gzip.compress(b"0 fabricated_rows 1 1_0\n", mtime=0))
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules


def test_a_deleted_vector_file_fails(tmp_path):
    proj = _project(tmp_path)
    S5.plant(proj)
    FH.main([str(proj)])
    (proj / "phase3/stage4/foundry_handoff/ate_patterns"
     / f"{S5.CASE}.vec.gz").unlink()
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules


def test_a_source_trace_that_is_not_step5s_passed_trace_fails(tmp_path):
    """A header whose source_trace names some other project file with its
    real hash does not close our item: the trace must be the one the Step-5
    record lists for that case in state passed."""
    proj = _project(tmp_path)
    rec = S5.plant(proj)
    FH.main([str(proj)])
    assert _gate(proj)[0] == 0
    rec["cases"][0]["state"] = "failed"
    (proj / S5.STEP5_REL).write_text(json.dumps(rec))
    rc, _rep, rules = _gate(proj)
    assert rc == 1 and CLOSED_RULE in rules
