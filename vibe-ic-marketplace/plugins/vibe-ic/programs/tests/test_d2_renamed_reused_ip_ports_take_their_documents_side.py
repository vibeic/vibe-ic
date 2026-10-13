#!/usr/bin/env python3
"""D2: a reused IP's RENAMED ports take the side the document gave the family,
and the document's illustrative names get no pad.

MEASURED on subservient x gf180mcuD (8HD-4, v1.25.64 @76a277544): step 15.5ic
refused PORT_WITHOUT_A_SIDE for 36 nets, the synthesised core's REAL SRAM
ports (`o_sram_waddr`, `o_sram_wdata`, `o_sram_wen`, ...). The pad population
came from L9 top_ports, which is the document's ports UNION the staged top's.
The L3 illustrative names (`o_sram_data`, `o_sram_addr`, `o_sram_we`, ...)
carry `declared_by_staged_top: false`, are absent from the netlist, and were
the ones the group rows "SRAM data bus" / "SRAM addr + control(we / cyc)"
resolved to. The real ports have atoms (wdata, waddr, wen) no row contains.

Two halves, both load-bearing:
  (A) an L9 entry labelled `declared_by_staged_top: false` and absent from the
      selected netlist is a document port the core does not have: no pad,
      recorded with its evidence;
  (B) a hand-authored SOURCE_MANIFEST `renamed_interfaces` pair carries its
      L9 names' group side to its RTL names, through the SAME exact-atom rule.
Remove (A) and the illustrative names get phantom pads; remove (B) and the
groups resolve to nothing (PAD_GROUP_UNRESOLVED).

The refusals that stay are pinned too: a pair spanning two groups is
PORT_ON_TWO_SIDES, no pair is PAD_GROUP_UNRESOLVED, a port nothing names is
PORT_WITHOUT_A_SIDE, and step 2's budget reads the same renames and refuses
the same contradictions first. The LibreLane chip path (the chip default)
runs the core-connection backstop before pad_assignment_gen.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

import _l_doc_pad_placement as LPP                      # noqa: E402
from _staged_top_module import EXTRACTION_STRATEGY as STAGED  # noqa: E402
import test_io_pad_chip_top_gen as IO                    # noqa: E402

GEN = PROGRAMS / "io_pad_chip_top_gen.py"
CHIP_TOP_V = "phase3/stage3/pnr/chip_top_io.v"

DOC = """---
layer: L3
---

# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **North (N)** | memory data bus |
| **South (S)** | memory addr + control(we) |
| **East (E)** | `clk` / `rst` |
| **West (W)** | status pin(s) |
"""


def _p(name, direction, staged, width=1, **extra):
    """An L9 entry. A staged one is what the phase-1 staged-top harvest ADDS
    (its extraction strategy is exactly the harvester's); a doc one is the
    document's own, labelled `declared_by_staged_top: false`."""
    port = {"name": name, "direction": direction, "width": width,
            "declared_by_staged_top": staged,
            "evidence": ("input/vendor_rtl/core.v" if staged
                         else "input/docs/L3_external_interface.md")}
    if staged:
        port["extraction_strategy"] = STAGED
    if width > 1:
        port.update(msb=width - 1, lsb=0)
    port.update(extra)
    return port


#: L9's reconciled list: the staged top's real ports, plus the document's
#: illustrative ones it labels `declared_by_staged_top: false`.
SPEC = {
    "top_module": "core",
    "top_ports": [
        _p("clk", "input", True), _p("rst", "input", True),
        _p("o_status", "output", True),
        _p("o_memory_wdata", "output", True, 2),
        _p("o_memory_waddr", "output", True),
        _p("o_memory_wen", "output", True),
        _p("o_memory_data", "output", False, 2),
        _p("o_memory_addr", "output", False),
        _p("o_memory_we", "output", False),
    ],
}

NETLIST = """module core(clk, rst, o_memory_wdata, o_memory_waddr, o_memory_wen, o_status);
  input clk;
  input rst;
  output [1:0] o_memory_wdata;
  output o_memory_waddr;
  output o_memory_wen;
  output o_status;
endmodule
"""

STAGED_TOP = """module core(input clk, input rst, output [1:0] o_memory_wdata,
  output o_memory_waddr, output o_memory_wen, output o_status);
endmodule
"""

PAIRS = [{"l9": ["o_memory_data"], "rtl": ["o_memory_wdata"]},
         {"l9": ["o_memory_addr", "o_memory_we"],
          "rtl": ["o_memory_waddr", "o_memory_wen"]}]

DOC_ONLY = {"o_memory_data", "o_memory_addr", "o_memory_we"}


def _project(tmp_path, *, pairs=PAIRS, reused_ip=True, doc=DOC, spec=SPEC,
             netlist=NETLIST):
    proj = IO._project(tmp_path, doc=doc, spec=spec)
    synth = proj / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "core_synth.v").write_text(netlist)
    if pairs is not None:
        rtl = proj / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(
            {"reused_ip": reused_ip, "renamed_interfaces": pairs}))
    return proj


def _gen(tmp_path, **kw):
    proj = _project(tmp_path, **kw)
    res = IO._run(GEN, proj, IO._pdk(tmp_path / "pdk"))
    return proj, res, res.stdout + res.stderr


def _refused(proj, res, out, rule):
    assert res.returncode == 1, out
    assert rule in out, out
    assert not (proj / CHIP_TOP_V).exists()


# --------------------------------------------------------------------------- #
# the measured shape: RED on main (PORT_WITHOUT_A_SIDE on the real ports)
# --------------------------------------------------------------------------- #
def test_renamed_ports_take_their_groups_side_and_doc_names_get_no_pad(tmp_path):
    proj, res, out = _gen(tmp_path)
    assert res.returncode == 0, out
    rec = IO._record(proj)
    sides = {k: set(v) for k, v in
             rec["derived_answers"]["pad_order_by_side"].items() if v}
    assert sides == {
        "north": {"u_pad_o_memory_wdata_1", "u_pad_o_memory_wdata_0"},
        "south": {"u_pad_o_memory_waddr", "u_pad_o_memory_wen"},
        "east": {"u_pad_clk", "u_pad_rst"},
        "west": {"u_pad_o_status"},
    }
    ports = {r["port"] for r in rec["pad_instances"].values()}
    assert not {p for p in ports if p.split("[")[0] in DOC_ONLY}
    wrapper = (proj / CHIP_TOP_V).read_text()
    for name in DOC_ONLY:
        assert f".{name}(" not in wrapper
    dropped = rec["doc_ports_not_implemented"]
    assert {d["name"] for d in dropped} == DOC_ONLY
    assert all(d["declared_by_staged_top"] is False and d["evidence"]
               and d["netlist"].endswith("core_synth.v") for d in dropped)
    via = {v["port"] for r in rec["pad_group_resolution"]
           for v in r["matched_via_rename"]}
    assert via == {"o_memory_wdata", "o_memory_waddr", "o_memory_wen"}


def test_the_wrapper_passes_the_runners_core_connection_backstop(tmp_path):
    import phase3_one_shot_runner as R
    proj, res, out = _gen(tmp_path)
    assert res.returncode == 0, out
    R._validate_padring_core_connections(
        proj / "phase2/stage2/synth/core_synth.v", proj / CHIP_TOP_V,
        "core", IO._record(proj).get("chip_top_module") or "chip_top")


def _selected_project(tmp_path, *, protocol=True, missing_mandatory=False,
                      wrong_width=False):
    doc_ports = [p for p in SPEC["top_ports"]
                 if p["name"] in DOC_ONLY or p["name"] in {"clk", "rst", "o_status"}]
    doc_ports = [{k: v for k, v in p.items()
                  if k not in {"declared_by_staged_top", "extraction_strategy"}}
                 for p in doc_ports]
    if missing_mandatory:
        doc_ports.append({"name": "i_required", "direction": "input", "width": 1})
    if wrong_width:
        doc_ports[0]["width"] = 4
    doc = DOC + """
## Memory interface examples
| Signal | Width | Direction | Description |
|---|---|---|---|
| `o_memory_data` (or `o_memory_wdata`) | 2 | output | data (typical) |
| `o_memory_addr` | 1 | output | address (typical) |
| `o_memory_we` | 1 | output | enable (typical) |
"""
    proj = _project(tmp_path, doc=doc,
                    spec={"top_module": "core", "top_ports": doc_ports})
    d = proj / "plugin_output"
    d.mkdir()
    choice = {"top_module": "core"}
    if protocol:
        choice["memory_interface_protocol"] = "split_read_write"
    (d / "declaration.json").write_text(json.dumps(choice))
    (d / "declaration.provenance.json").write_text(json.dumps(
        {"fields": {"top_module": {"provenance_verified": False}}}))
    return proj


def test_selected_declared_interface_rebinds_l9_and_the_normal_wrapper(tmp_path):
    import phase3_one_shot_runner as R
    proj = _selected_project(tmp_path)
    original_choice = (proj / "plugin_output/declaration.provenance.json").read_bytes()
    res = IO._run(GEN, proj, IO._pdk(tmp_path / "pdk"))
    assert res.returncode == 0, res.stdout + res.stderr
    R._validate_padring_core_connections(
        proj / "phase2/stage2/synth/core_synth.v", proj / CHIP_TOP_V,
        "core", "chip_top")
    l9 = json.loads((proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    assert l9["top_ports"] == l9["ports"] == l9["top_module_pins"]
    rows = {p["name"]: p for p in l9["top_ports"]}
    assert rows["o_memory_wdata"]["width"] == 2
    assert rows["o_memory_wdata"]["direction"] == "output"
    assert all(rows[n]["declared_by_staged_top"] is False for n in DOC_ONLY)
    assert (proj / "plugin_output/declaration.provenance.json").read_bytes() == original_choice


def test_selected_binding_keeps_input_and_implementation_evidence_distinct(tmp_path):
    import hashlib
    import phase1_doc_one_shot_runner as D
    from _staged_top_module import bind_selected_interface
    proj = _selected_project(tmp_path)
    l9 = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    original = json.loads(l9.read_text())
    bound = bind_selected_interface(proj, original)
    binding = bound["selected_interface_binding"]
    assert binding["top_module"] == "core"
    selected = proj / binding["selected_source"]
    assert binding["selected_source_sha256"] == hashlib.sha256(selected.read_bytes()).hexdigest()
    assert binding["provenance_verification"] == "NOT_VERIFIED_BY_INTERFACE_BINDING"
    assert binding["illustrative_groups"]
    assert not D._assert_no_rtl_oracle_leak_in_l_doc(bound, l9.name)
    added = [p for p in bound["top_ports"] if p.get("extraction_strategy") == STAGED]
    assert {p["name"] for p in added} == {"o_memory_wdata", "o_memory_waddr", "o_memory_wen"}
    for port in added:
        assert "Input interface delegation:" in port["evidence"]
        assert "input/docs/L3_external_interface.md" in port["evidence"]
        assert "Implemented name/direction/width: selected_interface_binding" in port["evidence"]
    assert bind_selected_interface(proj, bound) == bound
    # Exercise the real pad consumer, not a reader authored for this repair.
    from io_pad_chip_top_gen import _read_top_ports
    l9.write_text(json.dumps(bound))
    assert _read_top_ports(proj) == bound["top_ports"]


@pytest.mark.parametrize("control", ["current", "no_binding", "no_manifest",
                                     "no_input_authority", "required_source",
                                     "wrong_target_width", "conflicting_roster",
                                     "fixed_input_name", "negated_fixed_name",
                                     "rename_prohibited", "negated_prohibition"])
def test_spec_gate_consumes_current_selected_interface(tmp_path, control, capsys):
    """A producer projection retains examples; only current authority reconciles them."""
    import spec_conformance_check as SC
    from _staged_top_module import bind_selected_interface
    proj = _selected_project(tmp_path)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    bound = bind_selected_interface(proj, json.loads(path.read_text()))
    if control == "no_binding":
        bound.pop("selected_interface_binding")
    elif control == "no_manifest":
        (proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json").unlink()
    elif control == "no_input_authority":
        doc = proj / "input/docs/L3_external_interface.md"
        doc.write_text(doc.read_text().replace("(typical)", "")
                       .replace("(or `o_memory_wdata`)", ""))
    elif control in {"required_source", "wrong_target_width"}:
        for port in bound["ports"]:
            if control == "required_source" and port["name"] == "o_memory_addr":
                port["required"] = True
            elif control == "wrong_target_width" and port["name"] == "o_memory_wdata":
                port["width"] = 4
    elif control == "conflicting_roster":
        import copy
        bound["ports"] = copy.deepcopy(bound["ports"])
        for port in bound["ports"]:
            if port["name"] == "o_memory_addr":
                port["required"] = True
    elif control in {"fixed_input_name", "negated_fixed_name",
                     "rename_prohibited", "negated_prohibition"}:
        doc = proj / "input/docs/L3_external_interface.md"
        requirement = {
            "fixed_input_name": "address; mandatory fixed name; MUST implement o_memory_addr",
            "negated_fixed_name": "address; NOT a mandatory fixed name",
            "rename_prohibited": "address; o_memory_addr must not be renamed",
            "negated_prohibition": "address; No requirement that o_memory_addr must not be renamed",
        }[control]
        doc.write_text(doc.read_text().replace("address (typical)", requirement))
    path.write_text(json.dumps(bound))
    before = path.read_bytes()
    report = proj / "conformance.json"
    rc = SC.main(["--spec", str(path), "--rtl-dir",
                  str(proj / "phase2/stage2/synth"), "--json", str(report)])
    output = capsys.readouterr().out
    accepted = control in {"current", "negated_fixed_name", "negated_prohibition"}
    assert rc == (0 if accepted else 1), output
    assert path.read_bytes() == before  # The consumer validates without rewriting L9.
    findings = json.loads(report.read_text())
    if accepted:
        assert any(f["rule"] == "port-renamed-by-manifest" for f in findings)
        assert not any(f["severity"] == "ERROR" for f in findings)
    else:
        assert any(f["severity"] == "ERROR" for f in findings)


def test_selected_binding_does_not_relabel_forbidden_document_evidence(tmp_path):
    import phase1_doc_one_shot_runner as D
    from _staged_top_module import bind_selected_interface
    proj = _selected_project(tmp_path)
    l9 = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    content = json.loads(l9.read_text())
    for port in content["top_ports"]:
        if port["name"] in DOC_ONLY:
            port["evidence"] = "phase2/stage2/synth/core_synth.v: invented input authority"
    bound = bind_selected_interface(proj, content)
    violations = D._assert_no_rtl_oracle_leak_in_l_doc(bound, l9.name)
    assert violations and any("phase2/stage2/synth/core_synth.v" in v for v in violations)
    # Current implementation provenance does not excuse a contaminated input citation.
    assert any("ports" in v and "evidence" in v for v in violations)


@pytest.mark.parametrize("handoff", ["direct", "absent", "stale"])
def test_l9_regeneration_binds_staged_interface_before_synthesis(tmp_path, handoff):
    """The document producer consumes current staged RTL, before Step 9/L19.

    The implementation reader must still reject absent or stale handoffs;
    those artifacts cannot stop this earlier document producer.
    """
    import phase1_doc_one_shot_runner as D
    import phase3_one_shot_runner as R
    proj = _selected_project(tmp_path)
    source_doc = proj / "input/docs/L3_external_interface.md"
    source_doc.write_text(source_doc.read_text() + "\nTop-level module: core\n")
    docs = proj / "phase1/generated_docs"
    l9 = docs / "L9_INTEGRATION_SPEC.json"
    original = json.loads(l9.read_text())
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"ic_name": "core", "top_module": "core",
         "pin_table": [dict(p, mode=p["direction"])
                       for p in original["top_ports"]]}))
    l9.unlink()
    rtl = proj / "phase2/stage1/rtl/core.v"
    rtl.write_text(STAGED_TOP)
    switch = proj / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text(json.dumps({"steps": {"9": "direct" if handoff == "direct" else "librelane"}}))
    if handoff == "stale":
        # Synthetic malformed authority is a refusal control, never a receipt
        # fabricated to clear the real implementation gate.
        (proj / "phase2/stage2/synth/synth_inputs.json").write_text(
            json.dumps({"librelane_synthesis": {"schema": "obsolete"}}))
    extracted = {p.name: p.read_text() for p in (proj / "input/docs").glob("*.md")}
    assert not l9.exists()
    result = D.gen_l9_integration_spec(proj, extracted, {})
    final = json.loads(result.path.read_text())
    assert result.path == l9
    assert final["top_ports"] == final["ports"] == final["top_module_pins"]
    assert final["selected_interface_binding"]["selected_source"] == "phase2/stage1/rtl/core.v"
    assert {p["name"] for p in final["top_ports"]
            if p.get("declared_by_staged_top") is True} == {
                "clk", "rst", "o_status", "o_memory_wdata", "o_memory_waddr", "o_memory_wen"}
    if handoff != "direct":
        before = result.path.read_bytes()
        with pytest.raises(ValueError, match="LL_SYNTH_HANDOFF_INVALID"):
            R.pnr_input_netlist(proj, "core")
        assert result.path.read_bytes() == before


@pytest.mark.parametrize("control", ["top", "mandatory", "direction", "width"])
def test_l9_staged_binding_keeps_current_interface_mismatch_refusals(tmp_path, control):
    """Producer scope is not permission to ignore a current interface mismatch."""
    from _staged_top_module import refresh_selected_interface
    proj = _selected_project(tmp_path, missing_mandatory=control == "mandatory",
                             wrong_width=control == "width")
    rtl = proj / "phase2/stage1/rtl/core.v"
    rtl.write_text(STAGED_TOP)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    content = json.loads(path.read_text())
    if control == "top":
        content["top_module"] = "other_core"
    elif control == "direction":
        content["top_ports"][0]["direction"] = "output"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="differs from L9|mandatory_missing|direction mismatch|width mismatch"):
        refresh_selected_interface(proj, path, content, include_synthesis_handoff=False)
    assert path.read_bytes() == before


@pytest.mark.parametrize("control", ["mandatory", "direction", "width"])
def test_issue3067_l9_native_failure_preserves_prior_document(tmp_path, control):
    """Real regeneration must finish binding before replacing a prior L9."""
    import phase1_doc_one_shot_runner as D
    proj = _selected_project(tmp_path, missing_mandatory=control == "mandatory",
                             wrong_width=control == "width")
    source_doc = proj / "input/docs/L3_external_interface.md"
    source_doc.write_text(source_doc.read_text() + "\nTop-level module: core\n")
    rtl = proj / "phase2/stage1/rtl/core.v"
    rtl.write_text(STAGED_TOP)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    original = json.loads(path.read_text())
    if control == "direction":
        original["top_ports"][0]["direction"] = "output"
    path.write_text(json.dumps(original))
    (path.parent / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "core", "ic_name_extraction_strategy": "explicit_ic_name",
        "pin_table": [dict(p, mode=p["direction"]) for p in original["top_ports"]]}))
    switch = proj / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text(json.dumps({"steps": {"9": "librelane"}}))
    extracted = {p.name: p.read_text() for p in (proj / "input/docs").glob("*.md")}
    before = path.read_bytes()
    ok, result = D._v1_6_580_run_step_with_watchdog(
        lambda: D.gen_l9_integration_spec(proj, extracted, {}),
        step_name="L9_INTEGRATION_SPEC", layer_name="L9_INTEGRATION_SPEC",
        project=proj, timeout_s=30)
    assert (ok, result) == (False, None)
    assert path.read_bytes() == before
    outcome = D._pl.report_path(proj, "phase1/L9_INTEGRATION_SPEC_step_outcome.json")
    status = json.loads(outcome.read_text())
    assert status["phase1_step_error"] is True
    assert status["error_class"] == "ValueError"
    assert any(rule in status["error_message"] for rule in (
        "mandatory_missing", "direction mismatch", "width mismatch"))


def test_issue3067_first_optional_binding_needs_no_native_handoff(tmp_path):
    """Inline document facts survive absent later-stage implementation authority."""
    import phase1_doc_one_shot_runner as D
    import phase3_one_shot_runner as R
    project = tmp_path / "proj"
    source = project / "input/docs/integration.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Integration\n\nTop-level module: generic_top\n\n"
                      "```verilog\nmodule generic_top(input clk, input reset_n, "
                      "output data_o);\nendmodule\n```\n"
                      "\n| Pin | Direction | Description |\n|---|---|---|\n"
                      "| clk | input | clock input |\n"
                      "| reset_n | input | reset input |\n"
                      "| data_o | output | synchronous output |\n")
    choice = project / "plugin_output/declaration.json"
    choice.parent.mkdir()
    choice.write_text(json.dumps({"top_module": "generic_top"}))
    manifest = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"reused_ip": True}))
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"steps": {"9": "librelane"}}))
    extracted = {source.name: source.read_text()}
    D.gen_l1_datasheet(project, extracted)
    ok, result = D._v1_6_580_run_step_with_watchdog(
        lambda: D.gen_l9_integration_spec(project, extracted, {}),
        "L9_INTEGRATION_SPEC", "L9_INTEGRATION_SPEC", project, 30)
    assert ok is True and result is not None
    body = json.loads(result.path.read_text())
    assert body["top_module"] == "generic_top"
    assert {p["name"] for p in body["top_ports"]} == {"clk", "reset_n", "data_o"}
    assert "selected_interface_binding" not in body
    assert not body.get("phase1_step_error")
    before = result.path.read_bytes()
    with pytest.raises(ValueError, match="LL_SYNTH_HANDOFF_INVALID"):
        R.pnr_input_netlist(project, "generic_top")
    assert result.path.read_bytes() == before


def test_issue3067_watchdog_current_failure_survives_preserved_document(tmp_path):
    """A previous real document cannot hide this call's failure or recovery."""
    import phase1_doc_one_shot_runner as D
    project = tmp_path / "proj"
    document = D._pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json"
    document.parent.mkdir(parents=True)
    before = b'{"top_module":"neutral_top","ports":[],"prior_nonstub":true}\n'
    document.write_bytes(before)
    outcome = D._pl.report_path(project, "phase1/L9_INTEGRATION_SPEC_step_outcome.json")
    def fail():
        raise ValueError("neutral current binding failure")
    ok, result = D._v1_6_580_run_step_with_watchdog(
        fail, "L9_INTEGRATION_SPEC", "L9_INTEGRATION_SPEC", project, 30)
    assert (ok, result) == (False, None)
    assert document.read_bytes() == before
    first = json.loads(outcome.read_text())
    assert first["phase1_step_error"] is True
    assert first["error_message"] == "neutral current binding failure"
    sentinel = object()
    ok, result = D._v1_6_580_run_step_with_watchdog(
        lambda: sentinel, "L9_INTEGRATION_SPEC", "L9_INTEGRATION_SPEC", project, 30)
    assert ok is True and result is sentinel
    current = json.loads(outcome.read_text())
    assert current["phase1_step_error"] is False
    assert current["phase1_step_timeout"] is False
    assert "error_message" not in current
    assert document.read_bytes() == before


@pytest.mark.parametrize("kw", [{"protocol": False},
                                {"missing_mandatory": True},
                                {"wrong_width": True}],
                         ids=["undeclared-interface", "mandatory-port", "named-width"])
def test_selected_binding_preserves_contract_refusals(tmp_path, kw):
    import phase3_one_shot_runner as R
    proj = _selected_project(tmp_path, **kw)
    res = IO._run(GEN, proj, IO._pdk(tmp_path / "pdk"))
    if res.returncode == 0:
        with pytest.raises(ValueError, match="PADRING_CORE_PORT_CONNECTION_MISMATCH"):
            R._validate_padring_core_connections(
                proj / "phase2/stage2/synth/core_synth.v", proj / CHIP_TOP_V,
                "core", "chip_top")
    else:
        assert "SELECTED_INTERFACE_BINDING_REFUSED" in res.stdout + res.stderr


# --------------------------------------------------------------------------- #
# the refusals that stay
# --------------------------------------------------------------------------- #
def test_a_pair_spanning_two_groups_is_on_two_sides(tmp_path):
    # every name in the pair 2 bits wide, so phase 2 accepts it
    wide = {"o_memory_addr": False, "o_memory_waddr": True}
    spec = dict(SPEC, top_ports=[
        _p(p["name"], "output", wide[p["name"]], 2) if p["name"] in wide
        else p for p in SPEC["top_ports"]])
    netlist = NETLIST.replace("output o_memory_waddr;",
                              "output [1:0] o_memory_waddr;")
    pairs = [{"l9": ["o_memory_data", "o_memory_addr"],
              "rtl": ["o_memory_wdata", "o_memory_waddr"]},
             {"l9": ["o_memory_we"], "rtl": ["o_memory_wen"]}]
    proj, res, out = _gen(tmp_path, spec=spec, netlist=netlist, pairs=pairs)
    _refused(proj, res, out, "PORT_ON_TWO_SIDES")
    assert "renamed_interfaces_rejected" not in IO._record(proj)


@pytest.mark.parametrize("kw", [{"pairs": []}, {"pairs": None},
                                {"reused_ip": False}],
                         ids=["no-pair", "no-manifest", "not-reused-ip"])
def test_without_a_declared_rename_the_groups_are_unresolved(tmp_path, kw):
    _refused(*_gen(tmp_path, **kw), "PAD_GROUP_UNRESOLVED")


def test_an_implemented_port_nothing_names_has_no_side(tmp_path):
    spec = dict(SPEC, top_ports=SPEC["top_ports"] + [
        _p("o_memory_ren", "output", True)])
    netlist = NETLIST.replace("o_status);", "o_status, o_memory_ren);") \
        .replace("endmodule", "  output o_memory_ren;\nendmodule")
    _refused(*_gen(tmp_path, spec=spec, netlist=netlist),
             "PORT_WITHOUT_A_SIDE")


def test_an_exact_row_naming_a_dropped_doc_port_is_refused(tmp_path):
    """Renames carry sides through GROUP rows only (a deliberate choice: a
    per-bit mapping between an illustrative bus and its renamed parts is not
    stated anywhere). An exact row that names a doc-only port the core lacks
    is refused, never silently re-pointed."""
    doc = DOC.replace("| **North (N)** | memory data bus |",
                      "| **North (N)** | `o_memory_data[1:0]` |")
    _refused(*_gen(tmp_path, doc=doc), "PORT_WITHOUT_A_SIDE")


def test_an_unlabelled_or_staged_absent_port_is_never_dropped(tmp_path):
    """(A) reads L9's label, not absence alone: only `declared_by_staged_top
    is False` (or `optional is True`) AND absent is dropped."""
    import phase3_one_shot_runner as R
    import io_pad_chip_top_gen as G
    proj = _project(tmp_path)
    ports = [{"name": "clk"},
             {"name": "i_gone_unlabelled"},
             {"name": "i_gone_staged", "declared_by_staged_top": True},
             {"name": "i_gone_truthy", "declared_by_staged_top": 0},
             {"name": "i_gone_doc", "declared_by_staged_top": False}]
    orig = R.pnr_input_netlist
    try:
        R.pnr_input_netlist = lambda p, c: (
            proj / "phase2/stage2/synth/core_synth.v", "t", False)
        kept, dropped = G._drop_unimplemented_optional_ports(proj, ports)
    finally:
        R.pnr_input_netlist = orig
    assert [p["name"] for p in kept] == ["clk", "i_gone_unlabelled",
                                         "i_gone_staged", "i_gone_truthy"]
    assert [d["name"] for d in dropped] == ["i_gone_doc"]


def test_an_all_carrier_word_l9_name_carries_no_side():
    """`o_bus` has no semantic atom. The empty set is a subset of every
    statement, so without the non-empty guard its RTL names would land on
    every group side."""
    placement = LPP.parse_pad_placement(DOC, "L3.md")
    ports = [{"name": "o_memory_wdata", "width": 2}]
    grouped, records = LPP.resolve_declared_pad_groups(
        placement, ports, renames=[({"o_bus"}, {"o_memory_wdata"})])
    assert grouped == {}
    assert all(r["matched_via_rename"] == [] for r in records)


# --------------------------------------------------------------------------- #
# step 2 reads the same renames and refuses the same contradictions first
# --------------------------------------------------------------------------- #
def test_step2_and_the_ring_read_one_rename_list(tmp_path):
    proj = _project(tmp_path)
    ring = LPP.derive_own_ring(proj, [
        {"name": "clk"}, {"name": "rst"}, {"name": "o_status"},
        {"name": "o_memory_wdata", "width": 2},
        {"name": "o_memory_waddr"}, {"name": "o_memory_wen"}])
    assert ring["measurable"] and ring["groups_unresolved"] == []
    assert ring["by_side"]["N"] == ["o_memory_wdata[1]", "o_memory_wdata[0]"]
    assert ring["by_side"]["S"] == ["o_memory_waddr", "o_memory_wen"]
    assert ring["nets_on_two_sides"] == []
    assert ring["renamed_interfaces"] == [
        {"l9": sorted(p["l9"]), "rtl": sorted(p["rtl"])} for p in PAIRS]


_STEP2_L3 = """# L3 external interface

The I/O cell library is delegated to the PDK.

## Physical Pad Placement

| side | signals |
|---|---|
| E | `i_clk`, `i_rst` |
| N | sensor data bus |
| S | sensor addr + control (we) |
| W | gpio pin |
"""

_STEP2_RTL = ("module widget (input wire i_clk, input wire i_rst,\n"
              "  output wire [1:0] o_sensor_waddr, output wire [1:0] o_sensor_wdata,\n"
              "  output wire o_sensor_wen, output wire o_gpio);\n"
              "endmodule\n")

_STEP2_PAIRS = [{"l9": ["o_sensor_data"], "rtl": ["o_sensor_wdata"]},
                {"l9": ["o_sensor_addr"], "rtl": ["o_sensor_waddr"]},
                {"l9": ["o_sensor_we"], "rtl": ["o_sensor_wen"]}]

#: L9 for the step-2 design: the staged top's ports plus the document's
#: illustrative ones, as phase 1 writes it.
_STEP2_L9 = {"top_module": "widget", "top_ports": [
    _p("i_clk", "input", True), _p("i_rst", "input", True),
    _p("o_sensor_waddr", "output", True, 2),
    _p("o_sensor_wdata", "output", True, 2),
    _p("o_sensor_wen", "output", True), _p("o_gpio", "output", True),
    _p("o_sensor_data", "output", False, 2),
    _p("o_sensor_addr", "output", False, 2),
    _p("o_sensor_we", "output", False)]}


def _step2(pairs, l9=_STEP2_L9, rtl=_STEP2_RTL, l3=_STEP2_L3):
    import test_r0915101_a_die_budgets_against_its_own_pad_ring as R0915
    proj = R0915._project(rtl=rtl, l3=l3)
    if l9 is not None:
        docs = proj / "phase1/generated_docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    if pairs is not None:
        (proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json").write_text(
            json.dumps({"reused_ip": True, "renamed_interfaces": pairs}))
    return R0915._run(proj)


def test_step2_fits_through_a_declared_rename():
    rc, rep = _step2(_STEP2_PAIRS)
    assert (rc, rep["verdict"]) == (0, "FITS"), rep.get("reason")
    assert rep["derived_ring"]["groups_unresolved"] == []


def test_step2_names_the_unresolved_group_and_the_manifest_remedy():
    rc, rep = _step2(None)
    assert (rc, rep["verdict"]) == (1, "DOES_NOT_FIT")
    assert set(rep["derived_ring"]["groups_unresolved"]) == {"N", "S"}
    assert "renamed_interfaces" in rep["reason"]


def test_step2_refuses_a_rename_that_spans_two_groups():
    pairs = [{"l9": ["o_sensor_data", "o_sensor_addr"],
              "rtl": ["o_sensor_wdata", "o_sensor_waddr"]},
             {"l9": ["o_sensor_we"], "rtl": ["o_sensor_wen"]}]
    rc, rep = _step2(pairs)
    assert (rc, rep["verdict"]) == (1, "DOES_NOT_FIT")
    assert "o_sensor_wdata[1]" in rep["derived_ring"]["nets_on_two_sides"]
    assert "PORT_ON_TWO_SIDES" in rep["reason"]


# --------------------------------------------------------------------------- #
# the LibreLane chip path (the chip default) runs the core-connection
# backstop before its PAD_* assignment reaches the tool
# --------------------------------------------------------------------------- #
_CORE = "module core(a);\n  input a;\nendmodule\n"


@pytest.mark.parametrize("wrapper_text,finding,unknown", [
    (_CORE + "module chip_top(a, o_phantom);\n  input a;\n  output o_phantom;\n"
     "  core u_core (.a(a), .o_phantom(o_phantom));\nendmodule\n",
     "PADRING_CORE_PORT_CONNECTION_MISMATCH", "unknown=['o_phantom']"),
    (_CORE + "module chip_top(a);\n  input a;\n  core u_core (.a(a));\n"
     "endmodule\n", None, None),
], ids=["phantom-pad", "matching-wrapper"])
def test_the_librelane_chip_path_refuses_a_phantom_pad_before_assignment(
        tmp_path, monkeypatch, wrapper_text, finding, unknown):
    import phase3_one_shot_runner as R
    import librelane_contract as contract
    from _stated_eda_image import state_the_image
    from types import SimpleNamespace
    monkeypatch.delenv("VIBEIC_LIBRELANE_IMAGE", raising=False)
    monkeypatch.delenv("VIBEIC_LIBRELANE_PDK_ROOT", raising=False)
    state_the_image(monkeypatch)
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)
    wrapper = out_dir / "chip_top_io.v"
    wrapper.write_text(wrapper_text)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"pdk_root_host": str(tmp_path)}))
    monkeypatch.setattr(R, "_padring_chip_top_record", lambda p: {
        "core_module": "core", "chip_top_module": "chip_top",
        "chip_top_verilog": str(wrapper.relative_to(project))})
    monkeypatch.setattr(R, "pnr_input_netlist",
                        lambda p, core: (wrapper, "n", False))
    monkeypatch.setattr(R, "_padring_pdk_root_and_tree",
                        lambda pdk, c: ("/pdk", "probe_pdk"))
    execs = []

    def _exec(container, cmd, **k):
        execs.append(cmd)
        return 1, "", "stop here: the backstop has already been passed"
    monkeypatch.setattr(R, "_docker_exec", _exec)
    monkeypatch.setattr(contract, "run_chain", lambda *a, **k: pytest.fail(
        "the tool chain must not run"))
    pdk = SimpleNamespace(name="probe_pdk")
    result, consumer = R._prepare_librelane_floorplan_for_route(
        project, pdk, "c", out_dir, f"read_verilog {wrapper}\nlink_design chip_top\n",
        {"15": "direct", "15.5ic": "librelane"},
        io_view_discover=lambda *a: ([], []))
    assert result.status == "FAIL" and consumer is None
    if finding is None:
        # the backstop passed: the next step (pad_assignment_gen) was reached
        assert result.extras["finding"] == "LL_PAD_ASSIGNMENT_FAILED"
        assert len(execs) == 1 and "pad_assignment_gen.py" in execs[0]
    else:
        assert result.extras["finding"] == finding, result.detail
        assert result.detail.startswith(finding) and unknown in result.detail
        assert execs == []


# --------------------------------------------------------------------------- #
# a pair counts only when phase 2's rename acceptance rule accepts it
# (spec_conformance_check: port-rename-*); step 2 and 15.5ic apply it alike
# --------------------------------------------------------------------------- #
_IMPL = [{"name": "o_memory_wdata", "dir": "output", "width": 2},
         {"name": "o_memory_wen", "dir": "output", "width": 1},
         {"name": "o_status", "dir": "output", "width": 1}]


@pytest.mark.parametrize("pair,l9_extra,reason", [
    (({"o_memory_ghost"}, {"o_memory_wdata"}), [],
     "l9 'o_memory_ghost' is no L9 top_ports entry"),
    (({"o_status"}, {"o_memory_wdata"}), [_p("o_status", "output", False)],
     "l9 'o_status' is still an implemented port"),
    (({"o_memory_data"}, {"o_memory_rdata"}), [],
     "rtl 'o_memory_rdata' is no implemented port"),
    (({"o_memory_data"}, {"o_memory_wdata"}),
     [_p("o_memory_wdata", "output", False, 2)],
     "rtl 'o_memory_wdata' is a port L9 declares"),
    (({"o_memory_data"}, {"o_memory_wdata"}),
     [_p("o_memory_data", "input", False, 2)],
     "rtl 'o_memory_wdata' is output, l9 'o_memory_data' is input"),
    (({"o_memory_data"}, {"o_memory_wdata"}),
     [_p("o_memory_data", "output", False, 3)],
     "rtl 'o_memory_wdata' is 2 bit(s), l9 'o_memory_data' is 3"),
], ids=["l9-not-in-L9", "l9-still-implemented", "rtl-not-implemented",
        "rtl-declared-by-the-document", "direction-changes", "width-changes"])
def test_a_pair_phase2_rejects_carries_no_side(pair, l9_extra, reason):
    l9 = [_p("o_memory_wdata", "output", True, 2),
          _p("o_memory_wen", "output", True),
          _p("o_memory_data", "output", False, 2)]
    names = {p["name"] for p in l9_extra}
    l9 = [p for p in l9 if p["name"] not in names] + l9_extra
    accepted, rejected = LPP.accept_renames([pair], l9, _IMPL)
    assert accepted == []
    assert rejected == [{"l9": sorted(pair[0]), "rtl": sorted(pair[1]),
                         "reasons": [reason]}]


def test_an_accepted_pair_and_an_unreadable_interface():
    l9 = [_p("o_memory_wdata", "output", True, 2),
          _p("o_memory_data", "output", False, 2),
          # width unknown on one side: not compared, as at phase 2
          {"name": "o_memory_we", "direction": "output"}]
    pairs = [({"o_memory_data"}, {"o_memory_wdata"}),
             ({"o_memory_we"}, {"o_memory_wen"})]
    impl = _IMPL + [{"name": "o_memory_wen", "dir": "output", "width": None}]
    accepted, rejected = LPP.accept_renames(pairs, l9, impl)
    assert accepted == pairs and rejected == []
    # an interface nobody could read accepts NOTHING, never everything
    accepted, rejected = LPP.accept_renames(pairs, l9, None)
    assert accepted == [] and len(rejected) == 2
    assert all(r["reasons"] == ["the implemented interface could not be read"]
               for r in rejected)


def test_a_rejected_pair_cannot_clear_port_without_a_side(tmp_path):
    """The review's scenario: an implemented port no row names, and a manifest
    pair from a name L9 does not have whose atoms fit a group row. Phase 2
    rejects the pair (port-rename-undeclared-spec-port); 15.5ic must too."""
    spec = dict(SPEC, top_ports=SPEC["top_ports"] + [
        _p("o_dbg_status", "output", True)])
    netlist = NETLIST.replace("o_status);", "o_status, o_dbg_status);") \
        .replace("endmodule", "  output o_dbg_status;\nendmodule")
    pairs = PAIRS + [{"l9": ["o_data_memory"], "rtl": ["o_dbg_status"]}]
    proj, res, out = _gen(tmp_path, spec=spec, netlist=netlist, pairs=pairs)
    _refused(proj, res, out, "PORT_WITHOUT_A_SIDE")
    assert "o_dbg_status" in out
    rec = IO._record(proj)
    assert rec["renamed_interfaces_rejected"] == [{
        "l9": ["o_data_memory"], "rtl": ["o_dbg_status"],
        "reasons": ["l9 'o_data_memory' is no L9 top_ports entry"]}]


def test_a_width_changing_pair_leaves_its_group_unresolved(tmp_path):
    spec = dict(SPEC, top_ports=[
        p if p["name"] != "o_memory_data" else _p("o_memory_data", "output",
                                                  False, 3)
        for p in SPEC["top_ports"]])
    proj, res, out = _gen(tmp_path, spec=spec)
    _refused(proj, res, out, "PAD_GROUP_UNRESOLVED")
    rejected = IO._record(proj)["renamed_interfaces_rejected"]
    assert [r["rtl"] for r in rejected] == [["o_memory_wdata"]]
    assert "2 bit(s), l9 'o_memory_data' is 3" in rejected[0]["reasons"][0]


def test_step2_refuses_the_pair_phase2_rejects():
    pairs = [{"l9": ["o_sensor_data"], "rtl": ["o_sensor_wdata"]},
             {"l9": ["o_sensor_addr"], "rtl": ["o_sensor_waddr"]},
             # direction changes: phase 2 rejects it, so its bit gets no pad
             {"l9": ["o_sensor_we"], "rtl": ["o_sensor_wen"]}]
    l9 = dict(_STEP2_L9, top_ports=[
        p if p["name"] != "o_sensor_we" else _p("o_sensor_we", "input", False)
        for p in _STEP2_L9["top_ports"]])
    rc, rep = _step2(pairs, l9=l9)
    assert (rc, rep["verdict"]) == (1, "DOES_NOT_FIT")
    assert "o_sensor_wen" in rep["reason"]
    assert [r["rtl"] for r in rep["derived_ring"]
            ["renamed_interfaces_rejected"]] == [["o_sensor_wen"]]


# --------------------------------------------------------------------------- #
# step 2 refuses an unresolved group row on its own account, as 15.5ic does
# (PAD_GROUP_UNRESOLVED), even when no RTL bit is left without a pad
# --------------------------------------------------------------------------- #
def test_step2_refuses_a_group_row_whose_family_has_no_rtl_port():
    """W | `gpio pin` names a family the core does not implement: no RTL
    port, and no L9 entry the netlist carries. Every RTL bit is bonded by the
    other rows, so the unbonded count is 0; the row still resolves to
    nothing, which 15.5ic refuses."""
    rtl = _STEP2_RTL.replace(", output wire o_gpio);", ");")
    l9 = dict(_STEP2_L9, top_ports=[
        p if p["name"] != "o_gpio" else _p("o_gpio", "output", False)
        for p in _STEP2_L9["top_ports"]])
    rc, rep = _step2(_STEP2_PAIRS, l9=l9, rtl=rtl)
    assert rep["own_ring"]["unbonded_count"] == 0, rep.get("reason")
    assert rep["derived_ring"]["groups_unresolved"] == ["W"]
    assert (rc, rep["verdict"]) == (1, "DOES_NOT_FIT")
    assert "PAD_GROUP_UNRESOLVED" in rep["reason"]
    assert "have no pad" not in rep["reason"]


@pytest.mark.parametrize("consumer", ["scaffold", "shared_parser", "fidelity"])
@pytest.mark.parametrize("control", ["current", "no_delegation", "required_source",
                                     "wrong_width", "no_manifest_rename", "empty_rename_target", "forged_binding",
                                     "missing_selected_port", "conflicting_roster"])
def test_selected_interface_chosen_roster_reaches_phase2_consumers(tmp_path, consumer, control):
    """Use real current producer and consumers; retain the original L9 artifact."""
    import phase2_scaffold_gen as P2
    from _specrtl_common import extract_spec_contract
    from _staged_top_module import bind_selected_interface
    from spec_rtl_port_fidelity_check import load_spec
    proj = _selected_project(tmp_path)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    bound = bind_selected_interface(proj, json.loads(path.read_text()))
    if control == "no_delegation":
        declaration = proj / "plugin_output/declaration.json"
        declaration.write_text(json.dumps({"top_module": "core"}))
    elif control in {"required_source", "wrong_width"}:
        for port in bound["ports"]:
            if control == "required_source" and port["name"] == "o_memory_addr":
                port["required"] = True
            elif control == "wrong_width" and port["name"] == "o_memory_wdata":
                port["width"] = 4
    elif control in {"no_manifest_rename", "empty_rename_target"}:
        manifest = proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
        manifest.write_text(json.dumps({"reused_ip": True, "renamed_interfaces":
                                       [{"l9": sorted(DOC_ONLY), "rtl": []}]
                                       if control == "empty_rename_target" else []}))
    elif control == "forged_binding":
        doc = proj / "input/docs/L3_external_interface.md"
        doc.write_text(doc.read_text().replace("address (typical)",
                                               "address; mandatory fixed name; MUST implement o_memory_addr"))
        bound["selected_interface_binding"]["selected_source_sha256"] = "0" * 64
        # Forged labels cannot retire an input's now-fixed mandatory pin.
        bound["selected_interface_binding"]["document_examples_not_implemented"] = sorted(DOC_ONLY)
    elif control == "missing_selected_port":
        netlist = proj / "phase2/stage2/synth/core_synth.v"
        netlist.write_text(netlist.read_text().replace("o_memory_wdata, ", "")
                          .replace("  output [1:0] o_memory_wdata;\n", ""))
    elif control == "conflicting_roster":
        import copy
        bound["top_ports"] = copy.deepcopy(bound["top_ports"])
        bound["top_ports"][0]["width"] = 4
    path.write_text(json.dumps(bound))
    before = {p: p.read_bytes() for p in [path, proj / "phase2/stage2/synth/core_synth.v",
                                          proj / "plugin_output/declaration.provenance.json"]}
    def consume():
        if consumer == "scaffold":
            # The earlier L17 names must not put illustrative aliases back.
            l17 = {"channels": [{"name": name, "direction": "output"} for name in DOC_ONLY]
                               + [{"name": "o_memory_wdata", "direction": "output"}]}
            return P2.derive_signals(l17, bound, project=proj)
        if consumer == "shared_parser":
            return [vars(p) for p in extract_spec_contract(path.read_text(), is_json=True, project=proj).ports]
        return [vars(p) for p in load_spec(path)]
    if control == "current":
        rows = {p["name"]: p for p in consume()}
        assert set(rows) == {"clk", "rst", "o_status", "o_memory_wdata", "o_memory_waddr", "o_memory_wen"}
        assert rows["o_memory_wdata"]["width"] == 2
        assert rows["o_memory_wdata"]["direction"] == "output"
        assert not (set(rows) & DOC_ONLY)
    else:
        with pytest.raises((ValueError, KeyError), match=".+"):
            consume()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_selected_interface_actual_scaffold_and_conformance_handoff(tmp_path, capsys):
    import phase2_scaffold_gen as P2
    import spec_conformance_check as SC
    from _specrtl_common import parse_rtl_ports
    from _staged_top_module import bind_selected_interface
    proj = _selected_project(tmp_path)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    bound = bind_selected_interface(proj, json.loads(path.read_text()))
    path.write_text(json.dumps(bound))
    before = path.read_bytes()
    P2.emit_scaffold(proj)
    scaffold = proj / "phase2/stage1/scaffold/core_top.v"
    _, ports = parse_rtl_ports(scaffold.read_text(), "core")
    assert {p.name for p in ports} == {"clk", "rst", "o_status", "o_memory_wdata", "o_memory_waddr", "o_memory_wen"}
    report = proj / "chosen-conformance.json"
    rc = SC.main(["--spec", str(path), "--rtl-dir", str(proj / "phase2/stage2/synth"),
                  "--json", str(report)])
    assert rc == 0, capsys.readouterr().out
    assert not any(f["severity"] == "ERROR" for f in json.loads(report.read_text()))
    assert path.read_bytes() == before


def test_selected_interface_scaffold_requires_current_project(tmp_path):
    import phase2_scaffold_gen as P2
    from _staged_top_module import bind_selected_interface
    proj = _selected_project(tmp_path)
    path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    bound = bind_selected_interface(proj, json.loads(path.read_text()))
    with pytest.raises(ValueError, match="requires the current project"):
        P2.derive_signals({}, bound)
