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


def test_l9_regeneration_publishes_before_selected_handoff_read(tmp_path, monkeypatch):
    """Exercise the real emitter ordering with L9 absent at entry.

    This neutral fixture keeps the consumer's exact-name L9 read. The bounded
    actual-project control separately verifies the full native receipt/hash
    consumer, without replaying synthesis or inventing a generated L9.
    """
    import librelane_contract as LC
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
    observed = []

    def selected_handoff(project, top):
        current = LC._ldoc(project / "phase1/generated_docs", l9.name)
        assert current["top_module"] == top == "core"
        assert not current.get("phase1_step_error")
        observed.append(current)
        return project / "phase2/stage2/synth/core_synth.v", "fixture", False

    monkeypatch.setattr(R, "pnr_input_netlist", selected_handoff)
    extracted = {p.name: p.read_text() for p in (proj / "input/docs").glob("*.md")}
    assert not l9.exists()
    result = D.gen_l9_integration_spec(proj, extracted, {})
    final = json.loads(result.path.read_text())
    assert observed and result.path == l9
    assert final["top_ports"] == final["ports"] == final["top_module_pins"]
    assert final["selected_interface_binding"]["selected_source"].endswith("core_synth.v")
    assert {p["name"] for p in final["top_ports"]
            if p.get("declared_by_staged_top") is True} == {
                "clk", "rst", "o_status", "o_memory_wdata", "o_memory_waddr", "o_memory_wen"}


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
