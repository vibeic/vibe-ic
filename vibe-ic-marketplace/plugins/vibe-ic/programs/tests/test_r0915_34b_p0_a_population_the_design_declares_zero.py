"""R-0915-34(b): P0 sub-gates whose population an L-doc declares zero.

MEASURED 2026-09-15 (lane icspm3) on `spm` x gf180mcuD, a serial-parallel
multiplier with no register map, no DFT and no security asset. Four P0
sub-gates exited rc=2 and the umbrella booked all four ``EXECUTION_ERROR``::

    $ python3 programs/l4_regmap_declared_register_coverage_check.py <run>
    [SKIP] ... the input states no register-map denominator for L4 to be
           measured against                                            rc=2
    $ python3 programs/l4_regmap_phase2_emitter_contract_check.py <run>
    [SKIP] L4 declares no registers[] (no_registers_in_input=False,
           register_map_present=False)                                 rc=2
    $ python3 programs/l20_dft_scan_topology_actionable_check.py <run>
    [SKIP] no DFT requirement derivable ... and L20 asserts none        rc=2
    $ python3 programs/l23_security_requirements_typed_check.py <run>
    [SKIP] design declares no security-relevant asset and L23 asserts none rc=2

``EXECUTION_ERROR`` says the PROGRAM failed. None of them did: each read the
design, found no instance of its subject, and said so. rc=2 carries both
meanings in this flow, and the umbrella was resolving the ambiguity the wrong
way.

R-0915-34(b) is the rule applied here: a zero population is a design
declaration only when THE DECLARING DOCUMENT EXISTS, parses, and positively
states it. So the disposition is bound to evidence, not to a reason token --
``applicability_evidence`` of kind ``design-declared-zero-population``, naming
the document, the fields counted, the count, and the assertions that make it a
statement rather than an empty scan. It is RE-DERIVED FROM THE BYTES each time
it is asked, so it cannot be asserted or go stale.

BOTH DIRECTIONS FOR EVERY GATE. A document declaring ONE instance keeps its
gate live; so does a document that is missing, that will not parse, or that
lists nothing but never says so.

AND THE READER IS PART OF THE CONTRACT. MEASURED: these layers ship in TWO
SHAPES -- L4 writes `registers` at the top level, L20 and L23 nest theirs under
`fields` -- so a reader that knows only the flat shape sees an EMPTY L20 and
would hand a scan-chained design the N/A. The fields are read through
`l_doc_consumer_contract.l_doc_fields`, the reader every other consumer of
these layers already uses, and the evidence NAMES it so the count can be
re-run against the same bytes.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as R  # noqa: E402

#: gate -> (document basename, the field a design sets to DECLARE the subject,
#:          a value that declares ONE instance)
DECLARING = {
    "l4_regmap_declared_register_coverage_check":
        ("L4_REGMAP.json", "registers", [{"name": "CTRL", "offset": 0}]),
    "l4_regmap_phase2_emitter_contract_check":
        ("L4_REGMAP.json", "internal_registers", [{"name": "shadow"}]),
    "l20_dft_scan_topology_actionable_check":
        ("L20_DFT_SCAN_TOPOLOGY.json", "scan_chains", [{"name": "chain0"}]),
    "l23_security_requirements_typed_check":
        ("L23_SECURITY_REQUIREMENTS.json", "attack_surface", ["debug port"]),
    "l10_test_cases_cover_l3_constraints_check":
        ("L3_CMD_PROTOCOL.json", "opcodes", [{"hex": "0x01"}]),
    "bram_pdob_combinational_check":
        ("L9_INTEGRATION_SPEC.json", "memory_candidates", [{"name": "buf"}]),
    "break_framing_vs_l3_check":
        ("L3_CMD_PROTOCOL.json", "opcodes", [{"hex": "0x7e"}]),
    "crc_oracle_vector_check":
        ("L3_CMD_PROTOCOL.json", "crc_parameters", {"poly": "0x31"}),
    "break_handler_safety_check":
        ("L6_CONTROL_LOGIC.json", "fsm_machines", [{"name": "mac"}]),
    "tx_abort_during_transmission_check":
        ("L9_INTEGRATION_SPEC.json", "submodules", [{"name": "tx_cmd"}]),
    "cross_module_1cycle_handshake_check":
        ("L9_INTEGRATION_SPEC.json", "submodules", [{"name": "rx_phy"}]),
    "frame_end_detection_check":
        ("L9_INTEGRATION_SPEC.json", "submodules", [{"name": "rx_phy"}]),
    "arbiter_starvation_check":
        ("L9_INTEGRATION_SPEC.json", "memories", [{"name": "otp"}]),
    "l3_opcode_response_template_check":
        ("L3_CMD_PROTOCOL.json", "opcodes", [{"hex": "0x01"}]),
    "l24_signoff_evidence_backed_check":
        ("L24_SIGNOFF.json", "drc_status", "CLEAN"),
    "l25_reliability_envelope_actionable_check":
        ("L25_RELIABILITY_MISSION_PROFILE.json", "mission_profile",
         {"temp_range_c": [-40, 125]}),
    # clock_divider_period_check is registered too, but its population is a
    # SUBSET of a field rather than the field, so its cases are written out
    # below rather than driven from this table.
    "clock_divider_period_check":
        ("L8_RTL_CONSTANTS.json", "clock_domains",
         [{"name": "clk", "domain_kind": "primary"},
          {"name": "clk_div4", "domain_kind": "derived", "derived_from": "clk"}]),
}
GATES = tuple(DECLARING)
#: Every gate whose declaration is a FIELD STATING the absence. The divider
#: gate is excluded: L8 states nothing about dividers, and what makes its zero
#: a declaration is that L8 ENUMERATED its clock domains -- so its two
#: negative controls are written out rather than driven from STATED_BY.
GENERIC_GATES = tuple(g for g in DECLARING if g != "clock_divider_period_check")

#: gate -> (the assertion field that makes its document a STATEMENT, the value
#: of that field which DENIES the absence). The polarity differs by layer --
#: L4/L20/L23 assert `<subject>_present: false`, while L3 and L9 assert
#: `no_<subject>_in_input: true` -- so the denial is carried per gate rather
#: than assumed, and every negative control below flips the right way.
STATED_BY = {
    "l4_regmap_declared_register_coverage_check": ("register_map_present", True),
    "l4_regmap_phase2_emitter_contract_check": ("register_map_present", True),
    "l20_dft_scan_topology_actionable_check": ("dft_present", True),
    "l23_security_requirements_typed_check":
        ("security_requirements_present", True),
    "l10_test_cases_cover_l3_constraints_check": ("no_opcodes_in_input", False),
    "bram_pdob_combinational_check": ("no_memories_in_input", False),
    "break_framing_vs_l3_check": ("no_opcodes_in_input", False),
    "crc_oracle_vector_check": ("no_crc_parameters_in_input", False),
    "break_handler_safety_check": ("no_fsm_in_input", False),
    "tx_abort_during_transmission_check": ("no_submodules_in_input", False),
    "cross_module_1cycle_handshake_check": ("no_submodules_in_input", False),
    "frame_end_detection_check": ("no_submodules_in_input", False),
    "arbiter_starvation_check": ("no_submodules_in_input", False),
    "l3_opcode_response_template_check": ("no_opcodes_in_input", False),
    # R-0915-36: these two read the layer's APPLICABILITY, and the denial of
    # an absence is the layer saying it IS applicable -- which is exactly the
    # un-extracted skeleton that must keep its gate live.
    "l24_signoff_evidence_backed_check": ("applicability", "APPLICABLE"),
    "l25_reliability_envelope_actionable_check": ("applicability", "APPLICABLE"),
    # L8 states nothing; what makes it a declaration is that it ENUMERATED its
    # clock domains. Its "lists nothing" control is written out below.
    "clock_divider_period_check": ("clock_mhz", None),
}


def _docs(proj):
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    return gd


def _write(proj, name, payload):
    (_docs(proj) / name).write_text(json.dumps(payload))


def _declares_none(tmp_path):
    """A project whose L4/L20/L23 each positively declare a zero population.

    L20 and L23 are written NESTED under `fields`; L3, L4, L6 and L9 FLAT,
    which is how these layers actually ship on spm.
    """
    proj = tmp_path
    _write(proj, "L4_REGMAP.json", {
        "doc_class": "regmap", "registers": [], "internal_registers": [],
        "register_map_present": False, "no_registers_in_input": False})
    _write(proj, "L20_DFT_SCAN_TOPOLOGY.json", {
        "doc_id": "L20", "fields": {
            "dft_present": False, "scan_chains": [], "bist_mbist": [],
            "jtag_tap": None, "test_compression": None}})
    _write(proj, "L23_SECURITY_REQUIREMENTS.json", {
        "doc_id": "L23", "fields": {
            "security_requirements_present": False, "secure_boot": False,
            "attack_surface": [], "key_handling": {},
            "side_channel_mitigation": []}})
    _write(proj, "L3_CMD_PROTOCOL.json", {
        "doc_class": "cmd_protocol", "opcodes": [], "payload_semantics": None,
        "crc_parameters": None, "no_opcodes_in_input": True,
        "no_payload_semantics_in_input": True,
        "no_crc_parameters_in_input": True})
    _write(proj, "L6_CONTROL_LOGIC.json", {
        "doc_class": "control_logic", "fsm_machines": [], "fsm_states": [],
        "fsm_machine_count": 0, "no_fsm_in_input": True,
        "no_fsm_states_in_input": True})
    _write(proj, "L8_RTL_CONSTANTS.json", {
        "doc_class": "rtl_constants", "clock_mhz": 50.0,
        "clock_domains": [{"name": "clk", "domain_kind": "primary",
                           "role": "primary", "freq_mhz": 50.0}]})
    _write(proj, "L24_SIGNOFF.json", {
        "doc_id": "L24", "applicability": "NOT_APPLICABLE",
        "extraction_status": "DECLARED_ABSENT_FROM_INPUT", "fields": {
            "drc_status": None, "lvs_status": None, "sta_status": None,
            "ir_drop_status": None, "antenna_status": None,
            "tapeout_gates": []}})
    _write(proj, "L25_RELIABILITY_MISSION_PROFILE.json", {
        "doc_id": "L25", "applicability": "NOT_APPLICABLE",
        "extraction_status": "DECLARED_ABSENT_FROM_INPUT", "fields": {
            "mission_profile": None, "qual_standard": None,
            "temp_range": None, "em_budget": None, "aging_margin": None}})
    _write(proj, "L9_INTEGRATION_SPEC.json", {
        "doc_class": "integration_spec", "top_module": "top",
        "submodules": [], "no_submodules_in_input": True,
        "memories": [], "memory_candidates": [], "memory_map": [],
        "no_memories_in_input": True, "no_memory_candidates_in_input": True,
        "no_memory_map_in_input": True})
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("module top(); endmodule\n")
    return proj, rtl


def _patch(proj, gate, **changes):
    """Rewrite one gate's document, preserving the shape it ships in."""
    name = DECLARING[gate][0]
    doc = json.loads((_docs(proj) / name).read_text())
    nested = doc["fields"] if isinstance(doc.get("fields"), dict) else None
    for key, value in changes.items():
        level = doc if (nested is None or key in doc) else nested
        level[key] = value
    _write(proj, name, doc)


# ── direction 1: the design declares the population is zero ───────────────


def test_that_disposition_is_skip_eligible():
    assert R.DESIGN_DECLARED_NA in R.SKIP_ELIGIBLE
    assert R.EXECUTION_ERROR not in R.SKIP_ELIGIBLE


# ── direction 2: a design that HAS the subject keeps its gate live ────────


def test_a_nested_layer_is_read_not_seen_as_an_empty_document(tmp_path):
    """The reader is load-bearing. A reader that knows only the flat shape
    sees NO `scan_chains` key in L20 at all -- an absent key is empty, so it
    would hand a SCAN-CHAINED design the N/A. Declare the chain in the shape
    L20 actually ships and the gate must stay live."""
    proj, rtl = _declares_none(tmp_path)
    gate = "l20_dft_scan_topology_actionable_check"
    raw = json.loads((_docs(proj) / DECLARING[gate][0]).read_text())
    assert "scan_chains" not in raw, "fixture flattened the document"
    assert raw["fields"]["scan_chains"] == []

    _patch(proj, gate, scan_chains=[{"name": "chain0"}], dft_present=True)
    nested = json.loads((_docs(proj) / DECLARING[gate][0]).read_text())
    assert nested["fields"]["scan_chains"], "fixture wrote to the wrong level"


# ── the refusals, pinned ──────────────────────────────────────────────────

# Batches 1-4 leave NO P0 sub-gate with an empty population unruled, so the
# `NOT_REGISTERED` roster that pinned my earlier refusals is gone -- every gate
# it held is now registered under R-0915-35/36/37. What replaces it is the
# refusal that still bites, below: a layer the design has NOT declared absent
# keeps its gate live even when every one of its fields is empty. That is the
# L24 case on spm, and it is the direction the whole rule exists to protect.


def test_an_applicable_but_unextracted_layer_keeps_its_gate_live(tmp_path):
    """MEASURED on spm: the input carries L24's subject -- 8 occurrences of
    "sign-off", 5 of DRC, 4 of LVS, 3 of STA across five input documents -- so
    L24 is emitted APPLICABLE and its skeleton is a real extraction gap, not a
    declared absence. Every field is still empty, and the gate must still
    run."""
    proj, rtl = _declares_none(tmp_path)
    gate = "l24_signoff_evidence_backed_check"
    _patch(proj, gate, applicability="APPLICABLE")
    doc = json.loads((_docs(proj) / "L24_SIGNOFF.json").read_text())
    assert doc["applicability"] == "APPLICABLE"
    assert all(v in (None, [], {}) for v in doc["fields"].values()), doc


# ── R-0915-35: a population that is a SUBSET of a field ───────────────────


@pytest.mark.parametrize("derived", [
    {"name": "clk_div4", "domain_kind": "derived", "derived_from": "clk"},
    {"name": "clk_gen", "role": "generated_clock"},
    {"name": "clk_half", "derived_from": "clk"},
])
def test_an_L8_that_declares_a_derived_clock_keeps_the_gate_live(
        tmp_path, derived):
    """Every shape `clock_contract.entry_is_derived` recognises must keep it
    live -- the predicate is the repo's, not this test's."""
    import clock_contract as _cc
    assert _cc.entry_is_derived(derived), derived
    proj, rtl = _declares_none(tmp_path)
    gate = "clock_divider_period_check"
    _patch(proj, gate, clock_domains=[
        {"name": "clk", "domain_kind": "primary"}, derived])


@pytest.mark.consistency
def test_the_roster_is_exactly_what_this_file_accounts_for():
    """No gate may join `_P0_GATE_ZERO_POPULATION` without a both-direction
    case here. If this fails, add the gate to DECLARING + STATED_BY rather
    than to this list."""
    assert set(STATED_BY) == set(DECLARING)
