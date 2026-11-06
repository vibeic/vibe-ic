"""R-0915-101: on a DIE the slot budget IS the die's own pad ring, and it DECIDES.

MEASURED on subservient x gf180mcuD, two runs of the SAME design against the
SAME input (benchmark-data 8e436ceb, DIE, owner-attested):

  r46, tree a8c7a3e74 -- the gate answered `NOT_APPLICABLE` /
      `DESIGN_DECLARED_NA`: it fell through to the HARDMACRO route ("nobody's
      slot, so no budget"). Skip-eligible, so flow step 2 PASSed. That is the
      laundering `test_issue2277
      ::test_a_DIE_against_the_same_catalogue_still_gets_a_real_verdict`
      forbids.

  r47, tree 8efd02930 -- the DIE branch landed and now outranks that route, so
      the die is no longer exempt. But with `pad_signal_map` NOT_DETERMINED it
      answered `UNDECIDED` / `BLOCKED_BY_UPSTREAM`, which is not skip-eligible,
      so `flow_compliance_check` booked step 2
      `FAIL -- INCOMPLETE: the gate reports its input was applicable and was
      NOT examined`, step 4's 10/10 L10 oracles were voided as
      `dependency [2] = FAIL`, and Overall went `NOT_MEASURED`. Every digital
      IC on the IC path sat behind that one gate.

Neither answer is a verdict about this design's pad budget, and the design was
not silent about its pad ring either time: it states it in the pad-placement
section of its own external-interface document, which is exactly where
`io_pad_chip_top_gen` derives `pad_order_by_side` and `SIGNAL_MAP` from at step
15.5ic. R-0915-101 rules that the phase-2 budget must derive from that SAME
source and DECIDE.

THE READER IS ONE READER. `_l_doc_pad_placement.derive_own_ring` is what both
steps call, so a phase-2 budget and a phase-3 ring cannot disagree about which
pad carries which net. Measured on the r47 project copy: the step-2 gate
derives 31 signal pads and r46's phase-3 `io_pad_chip_top.json` recorded 31
signal pad instances (33 total, less the 2 supply pads).

WHAT IS STILL UNDECIDABLE, AND IS A FINDING BY NAME. A die that declares no
top-level port, and a die that states its ring in NEITHER place it may be
stated, are design-input gaps. They are booked `ZERO_DENOMINATOR` with a named
finding -- never `BLOCKED_BY_UPSTREAM`, which would send the reader to an
upstream step that generates the ring FROM the declaration the design did not
write.
"""
import json
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _l_doc_pad_placement as LPP                     # noqa: E402
import _owner_declared as _OD                          # noqa: E402
import _tapeout_declaration as TD                      # noqa: E402
import slot_pad_budget_check as S                      # noqa: E402
import test_slot_pad_budget_check as T                 # noqa: E402  slot fixture

_CLAUSE = ("slot_pad_budget_check . --json "
           "reports/phase2/gates/slot_pad_budget.json")

#: The measured shape: a core top that is NOT `chip_top`, so nothing here
#: passes because the clause's `--top` default happened to match.
_TOP = "widget"

#: The design's own interface, and its own pad ring, in its own words. One
#: side spells its signals out; the others state a design-owned GROUP, which
#: is the other legitimate L-doc shape and the one the measured design used.
_L3_WITH_RING = """# L3 external interface

The I/O cell library is delegated to the PDK.

## Physical Pad Placement

| side | signals |
|---|---|
| E | `i_clk`, `i_rst` |
| N | sensor data bus |
| S | sensor addr + control (we / cyc) |
| W | gpio pin |
"""

#: The SAME document with the two bus sides removed. The design still declares
#: every port; its ring now carries pads for only some of them, so the budget
#: must REFUSE. This is the "pads exceed the ring's capacity" direction.
_L3_RING_TOO_SMALL = """# L3 external interface

## Physical Pad Placement

| side | signals |
|---|---|
| E | `i_clk`, `i_rst` |
| W | gpio pin |
"""

_RTL = ("module %s (input wire i_clk, input wire i_rst,\n"
        "  output wire [9:0] o_sensor_addr, output wire [7:0] o_sensor_data,\n"
        "  input wire [7:0] i_sensor_data, output wire o_sensor_we,\n"
        "  output wire o_sensor_cyc, output wire o_gpio);\n"
        "endmodule\n") % _TOP

_RTL_NO_PORTS = "module %s;\nendmodule\n" % _TOP

_NO_SLOT = {"path": None, "slot": None, "absent_reason": "no operator applies"}


def _project(*, deliverable="DIE", operator_template=None, rtl=_RTL,
             l3=_L3_WITH_RING, top=_TOP):
    """A DIE whose 0.5ic left the operator's whole CATALOGUE on disk.

    That catalogue is the measured state on any PDK with a live shuttle, and it
    is what makes the route question load-bearing: `slots` is non-empty, so no
    "no slot files" path is reachable.
    """
    operator_template = _NO_SLOT if operator_template is None \
        else operator_template
    d = Path(tempfile.mkdtemp(prefix="r0915101_"))
    tmpl = d / "input" / "submission_template"
    (tmpl / "slots").mkdir(parents=True)
    (tmpl / "slots" / "slot_1x1.json").write_text(
        json.dumps(T._slot_ingested()))
    doc, _ = TD.merge_answers(TD.blank_declaration(),
                              {"deliverable": deliverable, "top_cell": top})
    _OD.attest(doc)
    assert not TD.validate(doc)
    (tmpl / "tapeout_declaration.json").write_text(json.dumps(doc))
    (d / "input" / "step_0_5ic_answers.json").write_text(json.dumps(_OD.attest({
        "schema": "vibe-ic/step_0_5ic_answers/1",
        "operator_template": operator_template,
        "answers": {"deliverable": deliverable, "top_cell": top},
    })))
    docs = d / "input" / "docs"
    docs.mkdir(parents=True)
    if l3 is not None:
        (docs / "L3_external_interface.md").write_text(l3)
    r = d / "phase2" / "stage1" / "rtl"
    r.mkdir(parents=True)
    (r / ("%s.v" % top)).write_text(rtl)
    return d


def _run(project):
    """The gate alone: `(rc, report)`."""
    rel = "reports/phase2/gates/slot_pad_budget.json"
    rc = S.main([str(project), "--json", rel, "--top", "chip_top"])
    p = project / rel
    return rc, (json.loads(p.read_text()) if p.is_file() else None)


# --------------------------------------------------------------------------- #
# (a) a DIE with declared ports DECIDES, and states the arithmetic
# --------------------------------------------------------------------------- #
def test_a_DIE_with_a_declared_ring_FITS_and_shows_its_numbers():
    """RED before this change: UNDECIDED / BLOCKED_BY_UPSTREAM, rc 2, because
    `pad_signal_map` is NOT_DETERMINED and the prose ring was never read."""
    rc, rep = _run(_project())
    assert rep is not None
    assert rep["verdict"] == "FITS", rep.get("reason")
    assert rc == 0
    assert rep["reason_class"] if False else "reason_class" not in rep
    assert rep["budget_basis"] == "37.5self:own_pad_ring"
    assert rep["ring_source"] == "l_doc:pad_placement"
    # THE ARITHMETIC, not a word. 29 signal bits are owed (10 + 8 + 8 + 1 + 1
    # + 1; `i_clk`/`i_rst` get dedicated pads and are not counted), and the
    # ring the design declares places a pad for every one of them.
    a = rep["own_ring_arithmetic"]
    assert a["signal_pads_owed"] == 29
    assert a["signal_pads_placed_by_the_ring"] == 29
    assert a["signal_pads_owed_with_no_pad"] == 0
    assert a["ring_capacity_pads"] == 31          # + i_clk + i_rst
    # The supply pair is STATED as an obligation and does not move the verdict:
    # which macro plays each polarity is read from the PDK at step 15.5ic.
    assert a["supply_pads_owed_minimum"] == 2
    assert a["supply_pads_selected"] is None
    assert a["supply_pads_selected_by"]["step"] == S.OWN_RING_STEP


def test_the_ring_comes_from_the_document_the_producer_reads():
    """One reader, not a second parser. The gate's ring and step 15.5ic's ring
    are the same function's output over the same file."""
    p = _project()
    _, rep = _run(p)
    assert rep["derived_ring"]["source"] == "input/docs/L3_external_interface.md"
    ring = LPP.derive_own_ring(
        p, [{"name": "o_sensor_addr", "width": 10},
            {"name": "o_sensor_data", "width": 8},
            {"name": "i_sensor_data", "width": 8},
            {"name": "o_sensor_we", "width": 1},
            {"name": "o_sensor_cyc", "width": 1},
            {"name": "o_gpio", "width": 1},
            {"name": "i_clk", "width": 1}, {"name": "i_rst", "width": 1}])
    assert ring["measurable"] is True
    assert sorted(ring["signal_map"]) == sorted(rep["own_ring"]
                                               ["declared_ring_signals"])


def test_the_typed_declaration_still_wins_when_the_design_wrote_one():
    """Nothing about the declared path changes: `pad_signal_map` is the typed
    spelling and it outranks the prose one."""
    p = _project()
    decl = p / "input" / "submission_template" / "tapeout_declaration.json"
    doc = json.loads(decl.read_text())
    doc, _ = TD.merge_answers(doc, {
        "pad_signal_map": {"u_pad_%s" % n: n for n in
                           (["o_sensor_addr[%d]" % i for i in range(10)]
                            + ["o_sensor_data[%d]" % i for i in range(8)]
                            + ["i_sensor_data[%d]" % i for i in range(8)]
                            + ["o_sensor_we", "o_sensor_cyc", "o_gpio"])}})
    _OD.attest(doc)
    decl.write_text(json.dumps(doc))
    rc, rep = _run(p)
    assert rep["verdict"] == "FITS"
    assert rep["ring_source"] == "declaration:pad_signal_map"
    assert rc == 0


# --------------------------------------------------------------------------- #
# (b) it DECIDES, so it can REFUSE
# --------------------------------------------------------------------------- #
def test_a_DIE_whose_ring_has_no_pad_for_every_pin_DOES_NOT_FIT():
    """The proof that the new branch decides rather than launders: one
    property changed -- two sides removed from the design's OWN ring -- and
    the same design now goes red with the pins named."""
    rc, rep = _run(_project(l3=_L3_RING_TOO_SMALL))
    assert rep["verdict"] == "DOES_NOT_FIT"
    assert rc == 1
    a = rep["own_ring_arithmetic"]
    assert a["signal_pads_owed"] == 29
    assert a["ring_capacity_pads"] == 3           # i_clk, i_rst, o_gpio
    assert a["signal_pads_owed_with_no_pad"] == 28
    assert "o_sensor_addr[9]" in rep["own_ring"]["unbonded_declared_bits"]
    assert "o_sensor_addr" in rep["reason"]


# --------------------------------------------------------------------------- #
# (c) the one undecidable case is a FINDING BY NAME
# --------------------------------------------------------------------------- #
def test_a_DIE_with_no_declared_port_is_a_named_design_input_gap():
    rc, rep = _run(_project(rtl=_RTL_NO_PORTS))
    assert rep["verdict"] == "UNDECIDED"
    assert rc == 2
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    assert rep["reason_class"] != "BLOCKED_BY_UPSTREAM"
    assert [f["rule"] for f in rep["findings"]] == ["DIE_DECLARES_NO_TOP_PORT"]
    assert rep["findings"][0]["owner"] == "design input"


def test_a_DIE_that_states_its_ring_nowhere_is_a_named_design_input_gap():
    """No `pad_signal_map`, and no pad-placement section either. The ring step
    15.5ic generates is generated FROM this declaration, so waiting for it
    would be waiting for the design to answer its own question."""
    rc, rep = _run(_project(l3=None))
    assert rep["verdict"] == "UNDECIDED"
    assert rc == 2
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    assert rep["reason_class"] != "BLOCKED_BY_UPSTREAM"
    assert [f["rule"] for f in rep["findings"]] == ["DIE_DECLARES_NO_PAD_RING"]


def test_an_unreadable_pad_document_is_not_a_document_that_said_nothing():
    """"I could not read it" must not arrive as "the design declared no ring"
    without naming the file. The document is present and its bytes are out of
    reach -- which is a different fact from a design that wrote no ring, and
    the reason must carry the file's name either way."""
    p = _project(l3=_L3_WITH_RING)
    bad = p / "input" / "docs" / "L3_external_interface.md"
    bad.chmod(0o000)
    try:
        _, rep = _run(p)
    finally:
        bad.chmod(0o644)
    assert rep["verdict"] == "UNDECIDED"
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    named = json.dumps(rep["documents_unreadable"]) + rep["reason"]
    assert "L3_external_interface.md" in named
    assert "could not be read" in rep["reason"]


# --------------------------------------------------------------------------- #
# (d) the HARDMACRO / IP route is untouched
# --------------------------------------------------------------------------- #
def test_a_HARDMACRO_that_bought_no_slot_is_unchanged():
    """The operator template is the HARDMACRO path's input and a die never
    needs one. That route's report must carry exactly the fields it carried
    before, and NONE of the die branch's."""
    p = _project(deliverable="HARDMACRO")
    rc, rep = _run(p)
    assert rc == 2
    assert rep["verdict"] == "NOT_APPLICABLE"
    assert rep["reason_class"] == "DESIGN_DECLARED_NA"
    assert rep["skip_kind"] == "class-not-applicable"
    assert rep["applicability_evidence"]["assertions"] == [
        {"path": "answers.deliverable", "equals": "HARDMACRO"}]
    for k in ("budget_basis", "ring_source", "own_ring",
              "own_ring_arithmetic", "derived_ring", "findings"):
        assert k not in rep, k


def test_a_HARDMACRO_that_DID_bind_a_slot_is_still_budgeted_on_that_slot():
    """A purchase is owed a budget, and it is measured against the OPERATOR's
    pad list -- not against the design's own ring."""
    _, rep = _run(_project(
        deliverable="HARDMACRO",
        operator_template={"path": "templates/t.yaml", "slot": "slot_1x1"}))
    assert rep["verdict"] != "NOT_APPLICABLE"
    assert rep.get("budget_basis") != "37.5self:own_pad_ring"
    assert "largest_digital_signal_pad_count" in rep


def test_the_HARDMACRO_route_ignores_a_pad_placement_document():
    """A die's ring source must not leak into the slot path: the same document
    is on disk in both, and only the die reads it."""
    _, rep = _run(_project(
        deliverable="HARDMACRO",
        operator_template={"path": "templates/t.yaml", "slot": "slot_1x1"}))
    assert "L3_external_interface.md" not in json.dumps(rep)


# --------------------------------------------------------------------------- #
# (e) the umbrella no longer books step 2 INCOMPLETE
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# the top-resolution fallback, which is a change on BOTH routes and is bounded
# --------------------------------------------------------------------------- #
# MEASURED on r46: the declaration answers `top_cell: chip_top` -- the wrapper
# step 15.5ic GENERATES -- while the RTL staged at step 2 carries the core. The
# integration spec's own `top_module` is the design's answer for which module
# the staged RTL is, and it is consulted LAST. These two tests fix the
# precedence so the fallback can never overrule an answer that already worked.
def _with_l9(project, top_module):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top_module, "top_ports": [{"name": "i_clk", "width": 1}]}))
    return project


def test_the_integration_spec_names_the_core_when_the_declaration_names_the_wrapper():
    """RED before this change: "the design declares NO top-level port" about a
    design that declares eight, because the only module tried was the wrapper
    that does not exist until step 15.5ic."""
    p = _project(top="chip_top")            # the declaration's answer
    (p / "phase2" / "stage1" / "rtl" / "chip_top.v").unlink()
    r = p / "phase2" / "stage1" / "rtl"
    (r / "widget.v").write_text(_RTL)       # the staged RTL is the CORE
    _with_l9(p, "widget")
    rc, rep = _run(p)
    assert rep["verdict"] == "FITS", rep.get("reason")
    assert rc == 0
    assert "L9_INTEGRATION_SPEC.json:top_module" in rep["top_source"]
    assert rep["top"] == "widget"


def test_the_integration_spec_is_consulted_LAST_and_overrules_nothing():
    """Bounded on purpose: a declaration whose `top_cell` IS in the staged RTL
    still wins, even when the integration spec names a different module."""
    p = _with_l9(_project(), "some_other_module")
    rc, rep = _run(p)
    assert rep["verdict"] == "FITS"
    assert rep["top"] == _TOP
    assert "L9_INTEGRATION_SPEC" not in rep["top_source"]


def test_the_fallback_reaches_the_SLOT_route_too_and_is_said_so():
    """This is a change on BOTH routes, not a die-only one: a HARDMACRO that
    bought a slot and whose declaration names the wrapper is now measured
    against that slot instead of refusing over an argument. The operator
    template is still required on that route -- only the top name moved."""
    p = _project(deliverable="HARDMACRO", top="chip_top",
                 operator_template={"path": "templates/t.yaml",
                                    "slot": "slot_1x1"})
    (p / "phase2" / "stage1" / "rtl" / "chip_top.v").unlink()
    (p / "phase2" / "stage1" / "rtl" / "widget.v").write_text(_RTL)
    _with_l9(p, "widget")
    _, rep = _run(p)
    assert "largest_digital_signal_pad_count" in rep     # the slot arithmetic
    assert rep.get("budget_basis") != "37.5self:own_pad_ring"
    assert rep["verdict"] in ("FITS", "FITS_AFTER_FOLD", "DOES_NOT_FIT")


def _geometry_operator_project(*, source_changes=None, l3=_L3_WITH_RING):
    project = _project(operator_template={"path": "input/operator/geometry.json", "slot": "geometry"}, l3=l3)
    source = project / "input/operator/geometry.json"
    source.parent.mkdir()
    raw = {"SLOT": "geometry", "DIE_AREA": "0 0 1000 1200", "SEAL_RING_WIDTH": 10,
           "PAD_MASK": "neutral_mask.gds", "FORBIDDEN_LAYERS": [{"name": "neutral", "layer": 12, "datatype": 0}]}
    raw.update(source_changes or {})
    source.write_text(json.dumps(raw))
    record = S._ST.slot_record(source, raw, source.parent)
    slots = project / "input/submission_template/slots"
    (slots / "geometry.json").write_text(json.dumps(record))
    # An unselected catalog entry does not define the purchased geometry's pads.
    (slots / "slot_1x1.json").write_text(json.dumps({"slot": "slot_1x1", "pads": {
        "lists": [{"key": "PAD_LIST", "raw": ["bidir[0].pad"], "count": 1}]}}))
    return project, source, record


def test_geometry_only_operator_measures_design_ring_without_claiming_physical_fit():
    project, source, record = _geometry_operator_project()
    before = source.read_bytes()
    rc, report = _run(project)
    assert rc == 0 and report["verdict"] == "FITS"
    assert report["budget_basis"] == "operator_geometry:design_pad_ring"
    assert report["operator_template_contract"]["kind"] == "GEOMETRY_ONLY"
    assert report["operator_template_contract"]["slots"][0]["source_sha256"] == record["source_sha256"]
    assert report["own_ring_arithmetic"]["ring_geometric_capacity_pads"] is None
    assert report["physical_fit_verdict"] == "NOT_MEASURED"
    assert source.read_bytes() == before
    answers = json.loads((project / "input/step_0_5ic_answers.json").read_text())
    assert answers["operator_template"]["slot"] == "geometry"


def test_geometry_operator_still_rejects_a_ring_with_unbonded_ports():
    project, _, _ = _geometry_operator_project(l3=_L3_RING_TOO_SMALL)
    rc, report = _run(project)
    assert rc == 1 and report["verdict"] == "DOES_NOT_FIT"
    if report.get("budget_basis") == "operator_geometry:design_pad_ring":
        assert report["own_ring"]["unbonded_count"] > 0


def test_geometry_operator_never_overrides_a_declared_fixed_pad_roster():
    project, _, _ = _geometry_operator_project(source_changes={"PAD_LIST": ["bidir[0].pad"]})
    rc, report = _run(project)
    assert rc != 0 and report["verdict"] != "FITS"
    assert report.get("operator_template_contract", {}).get("kind") != "GEOMETRY_ONLY"


def test_geometry_operator_cannot_turn_malformed_pad_fields_into_no_roster():
    project, _, _ = _geometry_operator_project(source_changes={"PAD_SOUTH": 123})
    rc, report = _run(project)
    assert rc != 0
    assert report.get("operator_template_contract", {}).get("kind") != "GEOMETRY_ONLY"


def test_geometry_operator_requires_real_positive_geometry():
    project, _, _ = _geometry_operator_project(source_changes={"DIE_AREA": "0 0 0 1200"})
    rc, report = _run(project)
    assert rc != 0
    assert report.get("operator_template_contract", {}).get("kind") != "GEOMETRY_ONLY"


def test_geometry_operator_requires_readable_unchanged_source():
    project, source, _ = _geometry_operator_project()
    source.write_text(source.read_text() + " ")
    rc, report = _run(project)
    assert rc != 0
    assert report.get("operator_template_contract", {}).get("kind") != "GEOMETRY_ONLY"
    source.rename(source.with_suffix(".retained.json"))
    assert _run(project)[0] != 0
