#!/usr/bin/env python3
"""The input said "when you set X, also set Y". Only X reached the build.

MEASURED DEFECT (vibe-ic#2089, lane icaes, opentitan_aes)
=========================================================
`L8_RTL_CONSTANTS.parameters[override=true]` carries every value the design
input STATES, and `design_one_shot_runner._apply_l8_param_overrides` applies
them to the auto-emitted chip_top. Neither carries what setting one OBLIGES.

The reproduction input states a masking parameter off and, in its own words
one paragraph later:

    "When disabling the masking, also an unmasked S-Box implementation needs
     to be selected using the corresponding compile-time Verilog parameter."

Only the first half reached L8. The wrapper applied ``SecMasking = 0`` alone,
the coupled S-Box parameter kept its vendor default, that default names a
variant the cell EXCLUDES from staging, and yosys aborted with
``Module `\\aes_sbox_dom' referenced ... is not part of the design``. The abort
was triaged as a synthesis failure and, one step on, as a ZERO denominator —
eight testbenches "errored at elaboration", which is not a functional result
at all.

This is not an implicit convention read into the document. The sentence states
it outright, and an independent reader of ONLY the design input derived the
same coupling without seeing the crash.

WHAT IS PINNED HERE, AND THE LINE IT MUST NOT CROSS
===================================================
Two properties, one per program:

  * PHASE 1 extracts the RELATION and the sentence — never a value. The
    grammar is small ("when <disabling|…> <TRIGGER>, … also … <OBLIGATION>")
    and the sentence must SAY it is about a parameter; that grounding is the
    mechanism, so it is what these tests pin. A sentence that DENIES the
    coupling is dropped (vibe-ic#712), because publishing a denied
    requirement is the failure that vocabulary exists to prevent.

  * THE EMITTER REFUSES, and does not choose. #586's refusal — "Choosing a
    different PRESENT variant would silently rewrite a parameter selection
    and is NOT done" — is untouched: the outcome is a refusal naming both
    parameters and quoting the input's own sentence, so the operator supplies
    the missing declaration. Nothing here proposes a value.

BOTH DIRECTIONS. A design whose input carries no coupling sentence must be
unchanged, and an input that states BOTH halves must pass — otherwise this is
a check that always fires, which is not a check.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _path_layout as _pl  # noqa: E402
import design_one_shot_runner as D  # noqa: E402
import phase1_doc_one_shot_runner as R  # noqa: E402

#: The reproduction sentence, verbatim from the cell's own input document.
COUPLING_SENTENCE = (
    "When disabling the masking, also an unmasked S-Box implementation needs "
    "to be selected using the corresponding compile-time Verilog parameter.")

_RTL = """module dut #(
  parameter bit         SecMasking  = 1,
  parameter sbox_impl_e SecSBoxImpl = SBoxImplDom,
  parameter int         WidthBits   = 8
) (input logic clk); endmodule
"""


def _input_project(tmp_path: Path, rtl: str = _RTL) -> Path:
    rtl_dir = tmp_path / "input" / "vendor_rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "dut.sv").write_text(rtl)
    return tmp_path


def _extract(project, docs, stated=("SecMasking",)):
    content = {"parameters": [{"name": n, "value": "0", "override": True}
                              for n in stated]}
    evidence = {}
    R._v2089_extract_param_couplings(project, docs, content, evidence)
    return content, evidence


# ── PHASE 1: the relation is extracted ───────────────────────────────────

def test_a_stated_coupling_is_extracted_with_its_own_sentence(tmp_path):
    project = _input_project(tmp_path)

    content, evidence = _extract(
        project, {"input/docs/theory.md": COUPLING_SENTENCE})

    got = content.get("parameter_couplings") or []
    assert len(got) == 1, (
        "the input states that disabling one parameter obliges another and "
        "L8 carried no such relation at all")
    c = got[0]
    assert c["trigger_parameter"] == "SecMasking", (
        "the trigger must be bound to the parameter the input actually "
        "states, not left as a phrase a consumer cannot act on")
    assert c["trigger_polarity"] == "disabled"
    assert c["sentence"] == COUPLING_SENTENCE, (
        "a refusal has to be able to quote the input's own words")
    assert c["source"] == "input/docs/theory.md"
    # The L8 evidence map caps a literal at 120 characters, so the entry
    # carries the sentence's head — asserting the whole 145 would be pinning
    # this test to a cap that belongs to `_v1_6_395_push_l8_evidence`.
    ev = evidence.get("input/docs/theory.md") or []
    assert [e["label"] for e in ev] == [
        "vibe_ic_2089_prose_parameter_coupling_grounded"], (
        "the coupling must leave extraction evidence like every other L8 fact")
    assert COUPLING_SENTENCE.startswith(ev[0]["literal"])
    assert len(ev[0]["literal"]) == 120


def test_the_relation_never_carries_a_value_for_the_coupled_parameter(tmp_path):
    """#586 stands: the flow states the obligation, it does not satisfy it."""
    project = _input_project(tmp_path)
    c = (_extract(project, {"d.md": COUPLING_SENTENCE})[0]
         ["parameter_couplings"][0])

    assert "value" not in c and "required_value" not in c


def test_a_sentence_that_is_not_about_a_parameter_is_rejected(tmp_path):
    """The grounding, not the grammar, is what makes this safe."""
    project = _input_project(tmp_path)
    docs = {"d.md": "When disabling the masking, also the clock is gated."}

    assert (_extract(project, docs)[0].get("parameter_couplings") or []) == []


def test_a_denied_coupling_is_dropped_and_the_drop_is_counted(tmp_path):
    """vibe-ic#712 — a denied sentence must never publish a requirement."""
    project = _input_project(tmp_path)
    docs = {"d.md": ("When disabling the masking, also no further "
                     "compile-time parameter needs to be selected.")}

    content, _ = _extract(project, docs)

    assert (content.get("parameter_couplings") or []) == []
    assert (content.get("extraction_strategy") or {}).get(
        "vibe_ic_2089_couplings_dropped_as_denied") == 1, (
        "a retraction that leaves no trace is the silent half of #712")


def test_a_coupled_parameter_the_sentence_NAMES_is_bound_by_name(tmp_path):
    project = _input_project(tmp_path)
    docs = {"d.md": ("When setting SecMasking, also SecSBoxImpl must be "
                     "selected using the corresponding parameter.")}

    c = (_extract(project, docs)[0]["parameter_couplings"])[0]

    assert c["trigger_parameter"] == "SecMasking"
    assert c["required_parameter"] == "SecSBoxImpl"


def test_an_input_with_no_coupling_sentence_produces_none(tmp_path):
    project = _input_project(tmp_path)
    docs = {"d.md": "The masking can be enabled or disabled at compile time."}

    assert (_extract(project, docs)[0].get("parameter_couplings") or []) == []


# ── THE EMITTER: half a coupled pair is REFUSED ──────────────────────────

def _l8_project(tmp_path: Path, couplings) -> Path:
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"parameters": [], "parameter_couplings": couplings}))
    return tmp_path


_DESCRIBED = [{
    "trigger_parameter": "SecMasking",
    "trigger_phrase": "masking",
    "trigger_polarity": "disabled",
    "required_parameter": "",
    "required_phrase": "also an unmasked S-Box implementation …",
    "sentence": COUPLING_SENTENCE,
    "source": "input/docs/theory.md",
}]
_NAMED = [dict(_DESCRIBED[0], required_parameter="SecSBoxImpl")]


def test_the_measured_defect_a_trigger_alone_is_refused(tmp_path):
    project = _l8_project(tmp_path, _DESCRIBED)

    refusals, undetermined = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0"})

    assert undetermined == []
    assert len(refusals) == 1, (
        "the input stated one half of a coupled pair and the emitter wrote "
        "the wrapper anyway; yosys reported it several steps later as an "
        "elaboration abort")
    r = refusals[0]
    assert r["reason"] == "COUPLED_PARAMETER_NOT_STATED"
    assert r["trigger_parameter"] == "SecMasking"
    assert COUPLING_SENTENCE in r["message"], (
        "a refusal that does not quote the sentence sends the operator "
        "looking for a rule this flow invented")
    assert "input/docs/theory.md" in r["message"]


def test_stating_the_other_half_removes_the_refusal(tmp_path):
    """THE GREEN DIRECTION. A check that cannot pass is not a check."""
    project = _l8_project(tmp_path, _DESCRIBED)

    refusals, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0", "SecSBoxImpl": "SBoxImplCanright"})

    assert refusals == []


def test_a_NAMED_coupled_parameter_decides_on_that_name_alone(tmp_path):
    project = _l8_project(tmp_path, _NAMED)

    missing, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0", "WidthBits": "16"})
    present, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0", "SecSBoxImpl": "SBoxImplCanright"})

    assert [r["required_parameter"] for r in missing] == ["SecSBoxImpl"], (
        "when the sentence NAMES the coupled parameter, some OTHER override "
        "must not satisfy it")
    assert present == []


def test_the_trigger_polarity_must_be_satisfied(tmp_path):
    """The coupling speaks about DISABLING; leaving it enabled says nothing."""
    project = _l8_project(tmp_path, _DESCRIBED)

    refusals, _ = D._l8_param_coupling_refusals(project, {"SecMasking": "1"})

    assert refusals == []


def test_a_trigger_value_that_is_not_boolean_is_undetermined(tmp_path):
    """NOT a refusal, and NOT a clean bill — the two must stay different."""
    project = _l8_project(tmp_path, _DESCRIBED)

    refusals, undetermined = D._l8_param_coupling_refusals(
        project, {"SecMasking": "SomeEnumValue"})

    assert refusals == []
    assert [u["reason"] for u in undetermined] == [
        "TRIGGER_VALUE_NOT_BOOLEAN"]


def test_a_sized_literal_is_read_as_the_boolean_it_is(tmp_path):
    project = _l8_project(tmp_path, _DESCRIBED)

    refusals, undetermined = D._l8_param_coupling_refusals(
        project, {"SecMasking": "1'b0"})

    assert undetermined == []
    assert [r["reason"] for r in refusals] == ["COUPLED_PARAMETER_NOT_STATED"]


def test_a_design_that_states_no_coupling_is_a_no_op(tmp_path):
    """Byte for byte unchanged on every design without such a sentence."""
    project = _l8_project(tmp_path, [])

    assert D._l8_param_coupling_refusals(
        project, {"SecMasking": "0"}) == ([], [])


def test_an_absent_layer_is_a_no_op(tmp_path):
    assert D._l8_param_coupling_refusals(
        tmp_path, {"SecMasking": "0"}) == ([], [])


def test_no_overrides_at_all_is_a_no_op(tmp_path):
    project = _l8_project(tmp_path, _DESCRIBED)
    assert D._l8_param_coupling_refusals(project, {}) == ([], [])


# ── THE STEP READS THE REFUSAL BACK ──────────────────────────────────────









# ── PHASE 1 (F21): the recommendation is CONDITIONAL ON THE TARGET ───────
# The coupling says a second parameter must be stated; the input's next
# sentence says which value to give it, and makes that conditional on the
# implementation target. The lane authored the FPGA variant for a design
# whose declared target is an open ASIC PDK — not because it misread the RTL,
# but because the recommendation never left the document.

RESPECTIVELY = ("When disabling masking, it is recommended to use the "
                "unmasked Canright or LUT S-Box implementation for ASIC or "
                "FPGA targets, respectively.")


def _recommendations(docs):
    content, evidence = {}, {}
    R._v2089_extract_target_recommendations(None, docs, content, evidence)
    return content, evidence


def test_respectively_distributes_the_recommendation_over_the_targets(tmp_path):
    """"A or B for X or Y, respectively" pairs A with X. Dropping the marker
    inverts half of every such sentence."""
    content, _ = _recommendations({"input/docs/theory.md": RESPECTIVELY})

    got = {r["target"]: r["recommends"]
           for r in content["target_conditional_recommendations"]}
    assert got == {"ASIC": "the unmasked Canright",
                   "FPGA": "LUT S-Box implementation"}
    assert all(r["distributive"] for r
               in content["target_conditional_recommendations"])
    # The recorded sentence is stable regardless of how the document wraps:
    # `sentence_scope` breaks before a full stop followed by a newline and
    # after one that ends the text, so the terminator is normalised away.
    assert {r["sentence"] for r
            in content["target_conditional_recommendations"]} == {
        RESPECTIVELY.rstrip(".")}


def test_a_labelled_bullet_recommends_its_own_subject(tmp_path):
    """"<name>: … , recommended when targeting <target>" recommends <name> —
    not the condition that follows the word."""
    docs = {"d.md": ("- Canright S-Box: only use when disabling masking, "
                     "recommended when targeting ASIC implementation\n")}

    content, _ = _recommendations(docs)

    assert [(r["target"], r["recommends"])
            for r in content["target_conditional_recommendations"]] == [
        ("ASIC", "Canright S-Box")]


def test_a_DENIED_recommendation_is_dropped_and_counted(tmp_path):
    """vibe-ic#712, MEASURED LIVE in this repo's corpus: a document says a
    variant "can also be used for FPGA synthesis, but this is NOT
    recommended". Publishing it would name the discouraged implementation as
    the FPGA recommendation."""
    docs = {"d.md": ("The latch-based register file can also be used for "
                     "FPGA synthesis, but this is not recommended.")}

    content, _ = _recommendations(docs)

    assert (content.get("target_conditional_recommendations") or []) == []
    assert (content.get("extraction_strategy") or {}).get(
        "vibe_ic_2089_recommendations_dropped_as_denied") == 1


def test_a_recommendation_with_no_target_condition_is_not_extracted(tmp_path):
    """This field is the TARGET-CONDITIONAL one. An unconditional
    recommendation belongs to whatever reads unconditional recommendations,
    and answering "which variant for this target" with it would be wrong."""
    docs = {"d.md": "It is recommended to use the unmasked S-Box."}

    assert (_recommendations(docs)[0]
            .get("target_conditional_recommendations") or []) == []


def test_a_mismatched_list_length_leaves_the_pairing_UNMADE(tmp_path):
    """Three alternatives, two targets: the marker cannot be honoured, so the
    pairing is not guessed — every target carries the whole phrase."""
    docs = {"d.md": ("It is recommended to use A or B or C for ASIC or FPGA "
                     "targets, respectively.")}

    got = _recommendations(docs)[0]["target_conditional_recommendations"]

    assert [r["target"] for r in got] == ["ASIC", "FPGA"]
    assert {r["recommends"] for r in got} == {"A or B or C"}
    assert not any(r["distributive"] for r in got)


def test_the_recommendation_carries_its_sentence_and_source(tmp_path):
    content, evidence = _recommendations({"input/docs/theory.md": RESPECTIVELY})
    r = content["target_conditional_recommendations"][0]

    assert r["source"] == "input/docs/theory.md"
    assert r["recommends_full_phrase"] == ("the unmasked Canright or LUT "
                                           "S-Box implementation")
    assert [e["label"] for e in evidence["input/docs/theory.md"]] == [
        "vibe_ic_2089_target_conditional_recommendation"] * 2


# ── THE EMITTER (F21): the DERIVED variant must follow the recommendation ─
# MEASURED on THIS tree at cd83d08a933c, against the reproduction input:
# `_chip_top_resolve_excluded_variant_params` narrows the survivors to an
# unmasked Canright variant and an unmasked LUT variant and then takes "the
# consuming module's own declared default" — the LUT one — for a design whose
# declared target is an open ASIC PDK, while the input recommends the Canright
# one by name for exactly that target. The lane that reported it (#2089 F21)
# was blamed for authoring the FPGA variant; the flow derived it.
#
# The fixture is the STRUCTURE, not a vocabulary: three variants behind one
# selector, the design's own `Masked` derivation, its own default, and one
# variant EXCLUDED from staging by the filename convention. It is the same
# shape `test_excluded_variant_param_is_derived_or_refused.py` pins, which is
# deliberate — that file pins the derivation, this one pins its tie-break.

WRAPPER_BLOCK = """#(
  parameter bit          SecMasking  = 0,
  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom
)"""

_SBOX_SV = """
module thing_sbox #(
  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut
) (input logic a, output logic b);

  localparam bit Masked = (SecSBoxImpl == SBoxImplCanrightMasked ||
                           SecSBoxImpl == SBoxImplCanrightMaskedNoreuse ||
                           SecSBoxImpl == SBoxImplDom) ? 1'b1 : 1'b0;

  if (!Masked) begin : gen_unmasked
    if (SecSBoxImpl == SBoxImplCanright) begin : gen_canright
      thing_sbox_canright u_sbox (.a(a), .b(b));
    end else begin : gen_lut
      thing_sbox_lut u_sbox (.a(a), .b(b));
    end
  end else begin : gen_masked
    if (SecSBoxImpl == SBoxImplDom) begin : gen_dom
      thing_sbox_dom u_sbox (.a(a), .b(b));
    end else if (SecSBoxImpl == SBoxImplCanrightMaskedNoreuse) begin :
        gen_canright_masked_noreuse
      thing_sbox_canright_masked_noreuse u_sbox (.a(a), .b(b));
    end else begin : gen_canright_masked
      thing_sbox_canright_masked u_sbox (.a(a), .b(b));
    end
  end
endmodule
"""

_THING_TOP = """
module thing_top #(
  parameter bit         SecMasking  = 1,
  parameter sbox_impl_e SecSBoxImpl = SBoxImplDom
) (input logic a, output logic b);
  thing_sbox #(.SecSBoxImpl(SecSBoxImpl)) u_sbox (.a(a), .b(b));
endmodule
"""

_LEAVES = ("thing_sbox_lut", "thing_sbox_canright",
           "thing_sbox_canright_masked",
           "thing_sbox_canright_masked_noreuse")


def _variant_project(tmp_path: Path, *, pdk_target=None, recommendations=()):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (tmp_path / "input").mkdir()
    (rtl / "thing_sbox.sv").write_text(_SBOX_SV)
    (rtl / "thing_top.sv").write_text(_THING_TOP)
    for leaf in _LEAVES:
        (rtl / f"{leaf}.sv").write_text(
            f"module {leaf} (input logic a, output logic b);\n"
            f"  assign b = a;\nendmodule\n")
    (tmp_path / "input" / "thing_sbox_dom.sv.unused-masked-scan-excluded"
     ).write_text("module thing_sbox_dom (input logic a, output logic b);\n"
                  "  assign b = a;\nendmodule\n")
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"target_conditional_recommendations": list(recommendations)}))
    if pdk_target is not None:
        (gd / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"pdk_target": pdk_target}}))
    return tmp_path, rtl


def _asic_row(recommends):
    return {"target": "ASIC", "recommends": recommends,
            "sentence": ("Canright S-Box: only use when disabling masking, "
                         "recommended when targeting ASIC implementation"),
            "source": "input/docs/theory.md", "distributive": False}


def test_the_declared_target_and_the_recommendation_decide_the_variant(tmp_path):
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row("Canright S-Box")])

    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert refusals == []
    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplCanright", (
        "the flow derived the variant the input recommends for the OTHER "
        "target, off the consuming module's own default")
    assert resolved["SecSBoxImpl"]["tie_break"] == (
        "the design input's target-conditional recommendation")
    prov = resolved["SecSBoxImpl"]["recommendation"]
    assert prov["declared_target"] == "ASIC"
    assert prov["recommends"] == "Canright S-Box"
    assert prov["matched_words"] == ["canright"]
    assert "SBoxImplCanright" in block


def test_control_with_no_declared_target_the_module_default_still_decides(tmp_path):
    """BYTE FOR BYTE the pre-#2089 answer. A run that declares no process
    gets the old fallback, never a guess at which target it is."""
    project, rtl = _variant_project(
        tmp_path, pdk_target=None,
        recommendations=[_asic_row("Canright S-Box")])

    _b, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert refusals == []
    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert resolved["SecSBoxImpl"]["recommendation"] is None


def test_a_recommendation_for_the_OTHER_target_is_not_used(tmp_path):
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[dict(_asic_row("LUT-based S-Box"), target="FPGA")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert resolved["SecSBoxImpl"]["recommendation"] is None, (
        "a row for a target this design did not declare must decide nothing")


def test_a_recommendation_matching_two_survivors_refuses_to_choose(tmp_path):
    """The whole sentence names BOTH variants. Two hits is an ambiguity and
    this defers to the fallback rather than taking the first."""
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row(
            "the unmasked Canright or LUT S-Box implementation")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert resolved["SecSBoxImpl"]["recommendation"] is None


def test_only_DISTINCTIVE_words_decide(tmp_path):
    """Every candidate for one parameter shares most of its name. A
    recommendation that mentions only the shared words matches all of them
    and must decide nothing."""
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row("the SBox Impl variant")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert resolved["SecSBoxImpl"]["recommendation"] is None


def test_a_recommendation_naming_nothing_in_the_survivor_set_falls_back(tmp_path):
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row("the Gizmo implementation")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"


def test_word_tokens_split_camelcase_and_drop_the_short_ones(tmp_path):
    assert D._chip_top_word_tokens("SBoxImplCanright") == {
        "sbox", "impl", "canright"}
    assert D._chip_top_word_tokens("LUT S-Box implementation") == {
        "lut", "box", "implementation"}
    assert D._chip_top_word_tokens("") == set()


def test_the_declared_target_is_ASIC_only_when_a_process_is_declared(tmp_path):
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True)
    assert D._chip_top_declared_target(tmp_path) == ""
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": ""}}))
    assert D._chip_top_declared_target(tmp_path) == "", (
        "an EMPTY declaration is not a declaration")
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": "gf180mcuD"}}))
    assert D._chip_top_declared_target(tmp_path) == "ASIC"


def test_a_DERIVED_default_satisfies_the_coupling(tmp_path):
    """A derivation IS a selection — made from the design's own RTL and
    recorded with its provenance. Refusing over it would stop a build the
    flow can honestly produce and send the operator to hand-declare a value
    the flow just derived on better evidence than they have."""
    project = _l8_project(tmp_path, _DESCRIBED)

    stated_only, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0"})
    with_derived, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0", "SecSBoxImpl": "SBoxImplCanright"})

    assert [r["reason"] for r in stated_only] == [
        "COUPLED_PARAMETER_NOT_STATED"]
    assert with_derived == []


def test_a_recommendation_that_NAMES_THE_VALUE_outright_still_decides(tmp_path):
    """The most machine-readable form a recommendation can take is the
    parameter value itself — and it is the case the shared-word subtraction
    exists for. Without it, naming `SBoxImplCanright` matches BOTH survivors
    on the words they share (`sbox`, `impl`), reads as an ambiguity and falls
    back to the module default: the recommendation spelled as plainly as it
    can be, ignored. MEASURED — this test is what makes that mutation die."""
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row("SBoxImplCanright")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplCanright"
    assert resolved["SecSBoxImpl"]["recommendation"]["matched_words"] == [
        "canright"]


# ── THE EMITTER END TO END: the two halves meet ──────────────────────────







# ── NAME RESOLUTION: an invented name is worse than no name ──────────────
# The trigger and the obligation are bound to a parameter NAME by two passes
# — an outright identifier match, then a CONCEPT match against the parameters
# this design's own input already STATES. A third pass, over every parameter
# the staged RTL declares, was written and then removed: MEASURED against the
# reproduction input's own 933 declared names it bound a name off one
# incidental word in 1 of 12 ordinary obligation clauses and 1 of 12 ordinary
# trigger phrases. Those two measurements are the tests below. A wrong name
# does not degrade — it REFUSES A BUILD while naming a parameter the sentence
# never mentioned.

_RESOLVE_UNIVERSE = ("SecMasking", "SecSBoxImpl", "KEYMGR_DEBUG_OFFSET",
                     "VH_REGISTER_ADDRESS_OFFSET", "MaskingLfsrWidth",
                     "SecAllowForcingMasks", "EnMask", "BitMask")


def test_an_obligation_clause_that_names_nothing_binds_nothing(tmp_path):
    """MEASURED: the word "debug" alone bound `KEYMGR_DEBUG_OFFSET`."""
    clause = ("also the debug interface has to be turned off with the "
              "relevant compile parameter")

    assert R._v2089_resolve_parameter(clause, _RESOLVE_UNIVERSE, ()) == ""


def test_a_trigger_phrase_that_names_nothing_binds_nothing(tmp_path):
    """MEASURED: "address decoding" bound `VH_REGISTER_ADDRESS_OFFSET`."""
    assert R._v2089_resolve_parameter(
        "address decoding", _RESOLVE_UNIVERSE, ("SecMasking",)) == ""


def test_the_concept_still_binds_against_what_the_input_STATES(tmp_path):
    """THE OTHER DIRECTION. Removing the loose pass must not remove the pass
    the reproduction actually needs: "the masking" names no identifier, and
    the concept matches 5 of this universe's names but exactly ONE of the
    parameters the input states."""
    assert R._v2089_resolve_parameter(
        "masking", _RESOLVE_UNIVERSE, ("SecMasking",)) == "SecMasking"
    assert R._v2089_resolve_parameter(
        "masking", _RESOLVE_UNIVERSE, ("SecMasking", "EnMask")) == "", (
        "two stated parameters speak about the concept — that is an "
        "ambiguity, and refusing one is the point")


def test_an_outright_identifier_is_taken_as_written(tmp_path):
    assert R._v2089_resolve_parameter(
        "also SecSBoxImpl must be selected via the parameter",
        _RESOLVE_UNIVERSE, ()) == "SecSBoxImpl"


# ── THE RECORDS MUST BE NAMED FOR WHAT THEY HOLD ─────────────────────────
# The satisfied set is the overrides the input STATED plus the defaults the
# emitter DERIVED. A field called `applied_overrides` carrying both would tell
# a reader the input had stated a value the emitter worked out — the same
# shape as a verdict field carrying two facts, which this repo has paid for
# before. Pinned, because a rename is invisible to every other test here.

def test_the_refusal_record_names_the_set_it_actually_holds(tmp_path):
    project = _l8_project(tmp_path, _NAMED)

    refusals, _ = D._l8_param_coupling_refusals(
        project, {"SecMasking": "0", "SomeDerivedParam": "7"})

    assert len(refusals) == 1
    r = refusals[0]
    assert r["satisfied_parameters"] == {"SecMasking": "0",
                                         "SomeDerivedParam": "7"}
    assert "applied_overrides" not in r, (
        "the set carries derived values too; naming it after the stated ones "
        "makes the record say the input declared something it did not")
    assert "neither stated by the input nor derived by this emitter" in \
        r["message"]


def test_the_recommendation_provenance_names_the_words_that_decided(tmp_path):
    """`matched_words` is the intersection that DECIDED, not the candidate's
    whole distinctive set — naming the latter would report words the
    recommendation never contained."""
    project, rtl = _variant_project(
        tmp_path, pdk_target="sky130A",
        recommendations=[_asic_row("SBoxImplCanright")])

    _b, resolved, _r = D._chip_top_resolve_excluded_variant_params(
        project, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})

    prov = resolved["SecSBoxImpl"]["recommendation"]
    assert prov["matched_words"] == ["canright"]
    assert "distinctive_words" not in prov
