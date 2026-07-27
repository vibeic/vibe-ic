"""ORGANIC #507 — the HDL enum harvester routed 2 of 25 declarations, and
L4's gate reported PASS over a register set missing 84 declared addresses.

Measured on a staged RV-CPU corpus at v1.7.73. The package the design
stages as its own ground truth declares 25 ``typedef enum`` types.
Exactly two had a destination — the two whose TYPE NAME carried a
vocabulary the harvester recognised (``*fsm*`` -> L6.fsm_states,
``*opcode*`` -> L3.opcodes). The other 23 had no destination and, worse,
no RECORD that they had none: members reached the L docs only where prose
elsewhere happened to repeat the name. One of the 23 declares 145
``CSR_<NAME> = 12'h<addr>`` bindings; L4 carried 61 of them, 84 were
absent, and::

    [PASS] l4_regmap_enumerated_values_typed_check: 2 multi-bit
           enum-eligible fields all carry typed code->meaning
           enumerated_values

That gate audits the fields that are PRESENT. It had no view of how many
registers the input declares, so a shortfall of any size sat behind its
PASS — a numerator with no denominator.

The fix has four parts, and each has its own section below:

  (1) ROUTING IS TOTAL. ``_hdl_enum.route_enum`` returns a decision for
      every declaration and ``EnumRouting`` refuses to be constructed
      without a reason. "No branch handles this kind" is expressible
      only as a written decision, never as silence.

  (2) AN ADDRESS-VALUED ENUM REACHES L4. Routed by the member set's
      SHAPE — names each bound to a distinct code in a space far wider
      than the set — never by a type-name allow-list. The name
      vocabulary is consulted FIRST so the two types it already decided
      keep their destination and their extraction_strategy stamp.

  (3) L4 GAINS A DENOMINATOR.
      ``l4_regmap_declared_register_coverage_check`` re-derives BOTH
      sides itself — declared from the input, carried from the emitted
      L4 — because a denominator its own producer computes can only ever
      confirm itself.

  (4) THE CAP STOPS DROPPING DECLARATIONS. ``registers[:128]`` was a
      bare slice that could only ever lose registers without saying so;
      a register the input DECLARES is now exempt and every cut is
      written down.

Chip-AGNOSTIC throughout: no vendor, part, type name or register
spelling participates in any decision. Every fixture below uses
synthetic, vendor-neutral names.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import _hdl_enum as H  # noqa: E402
import _gate_denominator as GD  # noqa: E402
import l4_regmap_declared_register_coverage_check as COV  # noqa: E402
import phase1_doc_one_shot_runner as P  # noqa: E402

COV_GATE = PLUGIN / "programs" / "l4_regmap_declared_register_coverage_check.py"
TYPED_GATE = PLUGIN / "programs" / "l4_regmap_enumerated_values_typed_check.py"

REPO_ROOT = PLUGIN.parent.parent.parent
TRACKED_PKG = (REPO_ROOT / "benchmark-data" / "ic" / "ibex" / "input"
               / "docs" / "ibex_pkg.sv")


# A package declaring one of each shape the router must tell apart.
# `map_e` is an address map: 10 names, each bound to a distinct code in a
# 12-bit space it fills 0.2% of. `mode_e` is a 2-bit encoding that
# exhausts its own space. `sel_e` states no codes at all.
PKG_SV = """
package block_pkg;
  typedef enum logic [11:0] {
    REG_ALPHA   = 12'h300,
    REG_BRAVO   = 12'h301,
    REG_CHARLIE = 12'h304,
    REG_DELTA   = 12'h305,
    REG_ECHO    = 12'h340,
    REG_FOXTROT = 12'h341,
    REG_GOLF    = 12'h7a0,
    REG_HOTEL   = 12'h7a1,
    REG_INDIA   = 12'hb00,
    REG_JULIET  = 12'hb03
  } map_e;

  typedef enum logic [1:0] {
    MODE_OFF  = 2'b00,
    MODE_LOW  = 2'b01,
    MODE_HIGH = 2'b10,
    MODE_MAX  = 2'b11
  } mode_e;

  typedef enum logic [2:0] {
    SEL_A,
    SEL_B,
    SEL_C
  } sel_e;

  typedef enum logic [3:0] {
    ST_IDLE,
    ST_RUN,
    ST_DONE
  } unit_fsm_e;

  typedef enum logic [6:0] {
    CMD_READ  = 7'h03,
    CMD_WRITE = 7'h23,
    CMD_SYNC  = 7'h0f
  } opcode_e;
endpackage
"""


def _enums(text=PKG_SV, fname="block_pkg.sv"):
    return {e["type_name"]: e for e in H.harvest_enums({fname: text})}


def _routes(text=PKG_SV, fname="block_pkg.sv"):
    return {r.type_name: r for r in H.routing_inventory({fname: text})}


def _gen_l4(docs):
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l4_regmap(proj, docs)
    return proj, json.loads(Path(res.path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (1) routing is TOTAL — no declaration can be silently undecided
# ---------------------------------------------------------------------------

def test_every_declaration_gets_a_decision_with_a_reason():
    routes = _routes()
    enums = _enums()
    assert set(routes) == set(enums), (
        "every harvested typedef enum must have exactly one routing "
        f"decision: {sorted(set(enums) ^ set(routes))}")
    for name, r in routes.items():
        assert r.reason.strip(), f"{name} was decided with no reason"
        assert r.rule.strip(), f"{name} names no rule"


def test_routing_decision_cannot_be_constructed_without_a_reason():
    """THE defect, at the type level. A router that CAN be silent will be
    silent again for the next shape nobody anticipated."""
    with pytest.raises(ValueError) as exc:
        H.EnumRouting(type_name="anything_e", rule=H.RULE_NO_DESTINATION,
                      reason="")
    assert "reason" in str(exc.value).lower()
    with pytest.raises(ValueError):
        H.EnumRouting(type_name="anything_e", rule="", reason="because")


def test_unrouted_declarations_say_which_condition_they_failed():
    routes = _routes()
    # A 2-bit code space is not an address space, and the refusal says so
    # with the number that failed.
    assert routes["mode_e"].destination is None
    assert "2 bit" in routes["mode_e"].reason, routes["mode_e"].reason
    # A member set stating no codes at all states no addresses.
    assert routes["sel_e"].destination is None
    assert "0 of 3" in routes["sel_e"].reason, routes["sel_e"].reason


def test_routing_summary_reports_no_undecided_declarations():
    s = H.routing_summary(list(_routes().values()))
    assert s["typedef_enums"] == 5
    assert s["undecided"] == 0
    assert s["by_destination"] == {
        H.DEST_L4_REGISTERS: 1,
        H.DEST_L6_FSM_STATES: 1,
        H.DEST_L3_OPCODES: 1,
        "(no destination)": 2,
    }, s["by_destination"]
    for d in s["decisions"]:
        assert d["reason"], d


# ---------------------------------------------------------------------------
# (2) the address-map SHAPE — and the name vocabulary still winning first
# ---------------------------------------------------------------------------

def test_address_valued_enum_routes_to_l4_by_shape_not_by_name():
    routes = _routes()
    assert routes["map_e"].destination == H.DEST_L4_REGISTERS
    assert routes["map_e"].rule == H.RULE_ADDRESS_MAP_SHAPE
    assert routes["map_e"].binding_count == 10
    # Renaming the type must not change the decision — that is what
    # "route by shape, not by a type-name allow-list" means.
    renamed = PKG_SV.replace("} map_e;", "} zzz_t;")
    assert _routes(renamed)["zzz_t"].destination == H.DEST_L4_REGISTERS


def test_type_name_vocabulary_is_consulted_first_so_nothing_regresses():
    """The two types the name already routed keep their destination even
    when their member set would also satisfy the shape rule."""
    routes = _routes()
    assert routes["unit_fsm_e"].destination == H.DEST_L6_FSM_STATES
    assert routes["unit_fsm_e"].rule == H.RULE_TYPE_NAME_VOCABULARY
    assert routes["opcode_e"].destination == H.DEST_L3_OPCODES
    assert routes["opcode_e"].rule == H.RULE_TYPE_NAME_VOCABULARY

    # Give an fsm-named type a member set that IS address-map shaped:
    # the name still decides, so the states do not land in the regmap.
    wide_fsm = PKG_SV.replace("} map_e;", "} ctrl_fsm_e;")
    r = _routes(wide_fsm)["ctrl_fsm_e"]
    assert r.destination == H.DEST_L6_FSM_STATES
    assert r.rule == H.RULE_TYPE_NAME_VOCABULARY


def test_declared_state_enum_keeps_its_extraction_strategy_stamp():
    """No-regression, end to end: the L6 harvester's stamp is unchanged."""
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l6_control_logic(proj, {"block_pkg.sv": PKG_SV})
    l6 = json.loads(Path(res.path).read_text(encoding="utf-8"))
    declared = [s for s in (l6.get("fsm_states") or [])
                if s.get("declared_type") == "unit_fsm_e"]
    assert len(declared) == 3, l6.get("fsm_states")
    for s in declared:
        assert s["extraction_strategy"] == "hdl_typedef_enum_state_v1_7_72"


def test_shapes_that_are_not_address_maps_are_refused_one_by_one():
    """Each refusal condition, exercised on its own, so a threshold that
    stops working cannot hide behind another one."""
    # too narrow a code space
    narrow = ("package p; typedef enum logic [2:0] {"
              + ", ".join(f"A{i} = 3'd{i}" for i in range(8))
              + "} t_e; endpackage")
    assert _routes(narrow, "p.sv")["t_e"].destination is None
    # too few bindings
    few = ("package p; typedef enum logic [11:0] {"
           + ", ".join(f"A{i} = 12'h{i:03x}" for i in range(4))
           + "} t_e; endpackage")
    assert _routes(few, "p.sv")["t_e"].destination is None
    # the space is being enumerated, not addressed
    dense = ("package p; typedef enum logic [7:0] {"
             + ", ".join(f"A{i} = 8'd{i}" for i in range(200))
             + "} t_e; endpackage")
    assert _routes(dense, "p.sv")["t_e"].destination is None
    # a map with holes states no address for the rest
    holed = ("package p; typedef enum logic [11:0] {"
             + ", ".join(f"A{i} = 12'h{i * 16:03x}" for i in range(9))
             + ", A_NOVALUE } t_e; endpackage")
    r = _routes(holed, "p.sv")["t_e"]
    assert r.destination is None
    assert "9 of 10" in r.reason, r.reason
    # a member whose literal carries an unknown bit states no address
    unknown = ("package p; typedef enum logic [11:0] {"
               + ", ".join(f"A{i} = 12'h{i * 16:03x}" for i in range(9))
               + ", A_X = 12'hx0 } t_e; endpackage")
    assert _routes(unknown, "p.sv")["t_e"].destination is None


def test_a_wider_map_with_the_minimum_bindings_is_admitted():
    """The floor is a floor, not an accident: exactly MIN bindings in a
    wide, sparse space is an address map."""
    n = H.MIN_ADDRESS_BINDINGS
    src = ("package p; typedef enum logic [11:0] {"
           + ", ".join(f"A{i} = 12'h{i * 32:03x}" for i in range(n))
           + "} t_e; endpackage")
    assert _routes(src, "p.sv")["t_e"].destination == H.DEST_L4_REGISTERS


# ---------------------------------------------------------------------------
# (2b) the address map REACHES L4
# ---------------------------------------------------------------------------

def test_declared_address_bindings_land_in_l4_registers():
    _proj, l4 = _gen_l4({"block_pkg.sv": PKG_SV})
    by_name = {r.get("name"): r for r in l4["registers"]}
    for name in ("REG_ALPHA", "REG_JULIET", "REG_GOLF"):
        assert name in by_name, sorted(by_name)
    alpha = by_name["REG_ALPHA"]
    assert alpha["address_int"] == 0x300
    assert alpha["address"] == "0x300"
    assert alpha["declared_type"] == "map_e"
    assert alpha["extraction_strategy"] == "hdl_typedef_enum_address_v1_7_74"
    assert "block_pkg.sv" in alpha["evidence"]
    # The shapes that are NOT address maps must not become registers.
    for name in ("MODE_OFF", "SEL_A", "ST_IDLE", "CMD_READ"):
        assert name not in by_name, (
            f"{name} is not a register address binding and must not be "
            f"routed into the register map")


def test_l4_states_its_denominator_against_the_input():
    _proj, l4 = _gen_l4({"block_pkg.sv": PKG_SV})
    den = l4["input_declared_registers"]
    assert den["declared"] == 10
    assert den["carried_at_emit"] == 10
    assert den["absent_at_emit"] == []
    assert den["sources"][0]["type_name"] == "map_e"
    assert den["sources"][0]["routing_rule"] == H.RULE_ADDRESS_MAP_SHAPE


def test_a_prose_captured_address_is_corroborated_not_duplicated():
    """An address a prose walker already carries must not produce a
    SECOND register at the same address — an ambiguous decode is what
    l4_regmap_phase2_emitter_contract_check blocks on."""
    registers = [{"name": "alpha", "address": "0x300", "address_int": 0x300,
                  "evidence": "input/docs/block.rst"}]
    evidence = {}
    rec = P._v1_7_74_merge_declared_register_bindings(
        registers, {"block_pkg.sv": PKG_SV}, evidence)
    assert rec["bindings"] == 10
    assert rec["already_carried"] == 1
    assert rec["appended"] == 9
    assert len(registers) == 10
    assert [r["address_int"] for r in registers].count(0x300) == 1
    prior = registers[0]
    assert prior["name"] == "alpha", "the prose record keeps its own name"
    assert prior["declared_name"] == "REG_ALPHA"
    assert prior["declared_type"] == "map_e"
    assert any("map_e" in str(c)
               for c in prior["corroborating_evidence"]), prior


def test_the_register_cap_never_drops_a_declared_binding():
    """`registers[:128]` could only ever lose registers without saying
    so. A declared one is now exempt, and the cut is written down."""
    prose = [{"name": f"p{i}", "address_int": i} for i in range(200)]
    declared = [{"name": f"D{i}", "address_int": 0x1000 + i,
                 "extraction_strategy": P._V1_7_75_DECLARED_STRATEGY}
                for i in range(20)]
    kept, record = P._v1_7_74_cap_registers(prose + declared)
    kept_names = {r["name"] for r in kept}
    for d in declared:
        assert d["name"] in kept_names, (
            f"{d['name']} was declared by the input and the cap dropped it")
    assert record["cap"] == P._L4_PROSE_REGISTER_CAP
    assert record["collected"] == 220
    assert record["dropped"] == 200 - P._L4_PROSE_REGISTER_CAP
    assert record["dropped_names"], "a cut with no names is a silent cut"
    # Order is preserved: the cap decides which entries survive, not
    # where they sit.
    assert [r["name"] for r in kept] == sorted(
        kept_names, key=lambda n: [r["name"] for r in prose + declared
                                   ].index(n))


def test_the_cap_record_is_emitted_even_when_nothing_is_cut():
    _kept, record = P._v1_7_74_cap_registers(
        [{"name": f"p{i}"} for i in range(3)])
    assert record["dropped"] == 0
    assert record["reason"], "the absence of a cut must be a stated fact"


def test_a_deduped_register_table_row_hands_over_what_it_knew():
    """Routing the declaration into L4 makes it the FIRST source for
    every address it declares, so the documentation rows that AGREE with
    it are deduped. Dropping such a row whole drops its name, its
    columns and its evidence line — 21 address literals left one doc's
    completeness denominator that way, taking it from 100% to 52%."""
    existing = {"name": "REG_ECHO", "address": "0x340", "address_int": 0x340,
                "access": "", "description": "",
                "extraction_strategy": P._V1_7_75_DECLARED_STRATEGY}
    row = {"addr_hex": "0x340", "name": "counter_a", "access": "RO",
           "description": "cycle counter",
           "evidence": {"source": "perf.txt", "line": 83,
                        "matched_token": "| ``counter_a`` | 0x340 |"}}
    assert P._v1_7_74_absorb_deduped_regmap_row(existing, row) is True
    assert existing["name"] == "REG_ECHO", (
        "the surviving record keeps its own name")
    assert existing["also_named"] == ["counter_a"]
    assert existing["access"] == "RO"
    assert existing["description"] == "cycle counter"
    assert row["evidence"] in existing["corroborating_evidence"]
    # The literal the DOCUMENT used survives in the layer, which is what
    # the input-completeness denominator reads.
    assert "0x340" in json.dumps(existing)
    # Idempotent: absorbing the same row twice adds nothing.
    assert P._v1_7_74_absorb_deduped_regmap_row(existing, row) is False
    assert existing["also_named"] == ["counter_a"]


def test_absorbing_never_overwrites_a_value_the_survivor_already_has():
    existing = {"name": "REG_ECHO", "access": "RW",
                "description": "declared", "address": "0x340"}
    row = {"addr_hex": "0x340", "name": "REG_ECHO", "access": "RO",
           "description": "documented"}
    P._v1_7_74_absorb_deduped_regmap_row(existing, row)
    assert existing["access"] == "RW"
    assert existing["description"] == "declared"
    assert "also_named" not in existing, (
        "an identical name is not an alias")


# ---------------------------------------------------------------------------
# (3) L4's denominator gate
# ---------------------------------------------------------------------------

def _project_with(pkg_text, l4_registers, extra_l4=None):
    proj = Path(tempfile.mkdtemp())
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "block_pkg.sv").write_text(pkg_text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    doc = {"schema_version": 2, "doc_class": "regmap",
           "registers": l4_registers}
    doc.update(extra_l4 or {})
    (gd / "L4_REGMAP.json").write_text(json.dumps(doc))
    return proj


def _run_cov(proj, out=None):
    cmd = [sys.executable, str(COV_GATE), str(proj)]
    if out:
        cmd += ["--json", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_gate_fails_when_the_input_declares_registers_l4_does_not_carry():
    proj = _project_with(PKG_SV, [
        {"name": "REG_ALPHA", "address": "0x300", "address_int": 0x300}])
    cp = _run_cov(proj)
    assert cp.returncode == 1, cp.stdout
    assert "declares 10" in cp.stdout
    assert "carries 1" in cp.stdout
    assert "missing 9" in cp.stdout
    assert "REG_BRAVO" in cp.stdout


def test_gate_passes_once_every_declared_binding_is_carried():
    regs = [{"name": n, "address_int": a} for n, a in (
        ("REG_ALPHA", 0x300), ("REG_BRAVO", 0x301), ("REG_CHARLIE", 0x304),
        ("REG_DELTA", 0x305), ("REG_ECHO", 0x340), ("REG_FOXTROT", 0x341),
        ("REG_GOLF", 0x7a0), ("REG_HOTEL", 0x7a1), ("REG_INDIA", 0xb00),
        ("REG_JULIET", 0xb03))]
    cp = _run_cov(_project_with(PKG_SV, regs))
    assert cp.returncode == 0, cp.stdout
    assert "carries all 10" in cp.stdout


def test_a_binding_carried_under_the_walkers_own_name_still_counts():
    """Matching on the ADDRESS as well as the name keeps this a coverage
    rule rather than a naming rule."""
    regs = [{"name": n.lower().replace("reg_", ""), "address_int": a}
            for n, a in (
                ("REG_ALPHA", 0x300), ("REG_BRAVO", 0x301),
                ("REG_CHARLIE", 0x304), ("REG_DELTA", 0x305),
                ("REG_ECHO", 0x340), ("REG_FOXTROT", 0x341),
                ("REG_GOLF", 0x7a0), ("REG_HOTEL", 0x7a1),
                ("REG_INDIA", 0xb00), ("REG_JULIET", 0xb03))]
    cp = _run_cov(_project_with(PKG_SV, regs))
    assert cp.returncode == 0, cp.stdout


def test_gate_is_not_applicable_and_says_why_when_nothing_declares_a_map():
    """No address-valued enum in the input: NOT APPLICABLE with a written
    reason, never a silent PASS."""
    only_modes = ("package p; typedef enum logic [1:0] "
                  "{ M0 = 2'b00, M1 = 2'b01 } m_e; endpackage")
    proj = _project_with(only_modes, [{"name": "x", "address_int": 0}])
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout
    summary = json.loads(out.read_text())
    assert summary["denominator"]["examined"] == 0
    assert summary["denominator"]["not_applicable_reason"]


def test_gate_output_satisfies_the_denominator_disclosure_contract():
    """Checked against the SHARED contract rather than restated here, so
    a change to the contract reaches this gate."""
    regs = [{"name": "REG_ALPHA", "address_int": 0x300}]
    for pkg in (PKG_SV, "package p; typedef enum logic [1:0] "
                        "{ M0 = 2'b00 } m_e; endpackage"):
        proj = _project_with(pkg, regs)
        out = proj / "cov.json"
        _run_cov(proj, out)
        summary = json.loads(out.read_text())
        assert GD.disclosure_violations(summary) == [], summary


def test_the_denominator_counts_both_sides_independently_of_phase1():
    """L4 may CLAIM whatever it likes; the gate re-derives both sides.

    A producer that computes the denominator for its own consumer can
    only ever confirm itself — that is how a dropped document left the
    coverage metric at 100%."""
    proj = _project_with(
        PKG_SV,
        [{"name": "REG_ALPHA", "address_int": 0x300}],
        extra_l4={"input_declared_registers": {
            "declared": 1, "carried_at_emit": 1, "absent_at_emit": []}})
    cp = _run_cov(proj)
    assert cp.returncode == 1, (
        "the gate trusted L4's own claim of a complete register set")
    assert "declares 10" in cp.stdout


def test_gate_honours_a_written_waiver():
    proj = _project_with(PKG_SV, [{"name": "REG_ALPHA",
                                   "address_int": 0x300}])
    (proj / "waivers.json").write_text(json.dumps({
        COV.WAIVER_KEY: ("Only the alpha register is architecturally "
                         "implemented; the rest are decode-only and "
                         "documented in the integration note.")}))
    cp = _run_cov(proj)
    assert cp.returncode == 0, cp.stdout
    assert "waived" in cp.stdout


# ---------------------------------------------------------------------------
# (3b) the gate the issue quotes now states what it examined
# ---------------------------------------------------------------------------

def test_typed_enum_gate_states_its_denominator_on_the_pass_path():
    regs = [{"name": "CTRL", "address": "0x0", "fields": [
        {"field_name": "MODE", "bits": "1:0",
         "description": "2'b00 idle, 2'b01 run",
         "enumerated_values": [{"code": "2'b00", "meaning": "idle"},
                               {"code": "2'b01", "meaning": "run"}]}]}]
    proj = _project_with(PKG_SV, regs)
    cp = subprocess.run([sys.executable, str(TYPED_GATE), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    first = cp.stdout.strip().splitlines()[0]
    assert "examined 1 multi-bit enum-eligible register fields" in first, first
    assert "l4_regmap_declared_register_coverage_check" in first, first


def test_typed_enum_gate_states_a_reason_when_it_examined_nothing():
    proj = _project_with(PKG_SV, [{"name": "CTRL", "address": "0x0",
                                   "fields": [{"field_name": "BUSY",
                                               "bits": "0"}]}])
    cp = subprocess.run([sys.executable, str(TYPED_GATE), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 2, cp.stdout
    assert "examined 0 multi-bit enum-eligible register fields" in cp.stdout
    assert "considered" in cp.stdout


# ---------------------------------------------------------------------------
# (5) no regression, proved by sweeping the tracked corpus
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TRACKED_PKG.is_file(),
                    reason="tracked HDL corpus not present in this checkout")
def test_tracked_package_routes_every_declaration_and_regresses_none():
    """The measured case, end to end on the tracked file.

    25 declarations, every one decided. The two the type-name vocabulary
    already routed keep their destination; the address map that had none
    now has one; the remaining 22 carry a written refusal."""
    inv = H.routing_inventory({TRACKED_PKG.name: TRACKED_PKG.read_text()})
    assert len(inv) == 25
    by_dest = H.routing_summary(inv)["by_destination"]
    assert by_dest[H.DEST_L6_FSM_STATES] == 1
    assert by_dest[H.DEST_L3_OPCODES] == 1
    assert by_dest[H.DEST_L4_REGISTERS] == 1
    assert by_dest["(no destination)"] == 22
    for r in inv:
        assert r.reason.strip(), r.type_name
    l4 = [r for r in inv if r.destination == H.DEST_L4_REGISTERS][0]
    assert l4.binding_count == 145
    assert l4.rule == H.RULE_ADDRESS_MAP_SHAPE


@pytest.mark.skipif(not (REPO_ROOT / "benchmark-data").is_dir(),
                    reason="tracked HDL corpus not present in this checkout")
def test_shape_tier_adds_no_destination_to_a_name_routed_type_in_the_corpus():
    """Corpus sweep, not inspection: over every tracked HDL file, the
    shape tier must never take a declaration the name tier already
    decided, and must never route a non-map into the register map."""
    root = REPO_ROOT / "benchmark-data"
    files = []
    for suf in sorted(H.HDL_SUFFIXES):
        files.extend(root.rglob("*" + suf))
    seen = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "typedef" not in text or "enum" not in text:
            continue
        for enum in H.harvest_enums({p.name: text}):
            seen += 1
            decision = H.route_enum(enum)
            if enum.get("enum_role") is not None:
                assert decision.rule == H.RULE_TYPE_NAME_VOCABULARY, (
                    f"{p}:{enum['type_name']} was decided by the name tier "
                    f"before this change and is now decided by "
                    f"{decision.rule}")
            if decision.destination == H.DEST_L4_REGISTERS:
                ok, why = H.address_map_verdict(enum)
                assert ok, f"{p}:{enum['type_name']} routed to L4 but {why}"
    assert seen > 0, "the sweep found no typedef enum to sweep"
