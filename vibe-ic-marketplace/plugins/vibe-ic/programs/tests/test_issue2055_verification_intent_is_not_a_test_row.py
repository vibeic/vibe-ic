"""A verification-INTENT sentence is not a functional-test row (#2055).

MEASURED, u_hawaii_adc at v1.17.83 (lane czadc28, front door, image 0.3.46,
no timeout): Phase 2 halted at `step4_functional_evidence` on

    0 functional tests ran for 4 declared L10/L12 row(s)

All four rows carried `kind: verification_intent`.  Phase 1's L10 extractor had
promoted them from the input's `## Verification intent` bullet list, and two of
them were not verification statements about the design at all:

  * a TOOL-DISCLOSURE paragraph — which corner libraries the PDK ships, and
    that the results are simulated rather than silicon;
  * a GOLDEN CROSS-CHECK note — compare the design against a fabricated part
    and its extracted netlist, which §4.05 forbids reading at DESIGN time.

Neither TB producer could author them (`l10_unit_tb_gen`: "0 in scope, 4 out of
scope"), so Step 4 demanded execution of four things, two of which can never be
executed by construction, and reported the shortfall in a sentence that named
neither fact.  Three lanes read that wall as a defect in the RTL.

The tests below pin BOTH directions:

  * the two families are refused, each with its reason NAMED and RECORDED —
    delete either refusal and the sentence becomes a row again;
  * a genuine acceptance sentence is still a row, byte for byte.  The refusal
    NARROWS what the extractor emits, so the no-leak arms carry real analog and
    digital acceptances, a comparison that names no oracle, and an oracle noun
    with no comparison, and prove each one survives.

chip-AGNOSTIC throughout: documentation-role English, comparison verbs and
oracle-role nouns.  No chip, vendor, SKU, part number, process node or PDK
literal appears in this file.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P  # noqa: E402
import cpu_functional_oracle_waiver_check as C  # noqa: E402
import testbench_gen as TB  # noqa: E402

# ---------------------------------------------------------------------------
# The arms below drive the REAL extractor, never the private predicate.
#
# A control has to be runnable by the code it is controlling.  Calling
# `_v2055_refuse_verification_intent` directly makes every arm raise
# AttributeError on the pre-fix tree, and an arm that cannot run there observes
# nothing: the no-leak arms must PASS on both trees (a real acceptance was a row
# before and is a row still) while the refusal arms must FAIL on the pre-fix
# tree with the sentence still sitting in `test_cases`.
# ---------------------------------------------------------------------------
def _l5_doc(bullets) -> str:
    body = "\n".join(f"- {b}" for b in bullets)
    return ("# Analog spec\n\n"
            "## Verification intent (drives L7)\n"
            f"{body}\n\n"
            "## Something else\n- not a verification bullet\n")


def _run_l10(bullets):
    """Run the real L10 extractor over one `## Verification intent` list.

    A sibling L9 is written first because the anchor rule draws its observable
    vocabulary from the design's OWN other L-docs — which is exactly the order
    the runner emits them in (L9 at step 10, L10 at step 11)."""
    root = Path(tempfile.mkdtemp(prefix="i2055_"))
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_ports": [{"name": n} for n in sorted(OBSERVABLES)]}))
    P.gen_l10_test_cases(root, {"L5_ANALOG_SPEC.md": _l5_doc(bullets)}, {})
    doc = json.loads(
        (root / "phase1" / "generated_docs" / "L10_TEST_CASES.json")
        .read_text(errors="replace"))
    return doc.get("fields", doc)


def _verdict(sentence):
    """(became_a_row, refusal_record_or_None) for one bullet, end to end."""
    doc = _run_l10([sentence])
    rows = [c for c in doc.get("test_cases") or []
            if c.get("stimulus") == sentence]
    refusals = [r for r in doc.get("verification_intent_refusals") or []
                if r.get("sentence") == sentence]
    return bool(rows), (refusals[0] if refusals else None)


# The design's own name vocabulary, as `harvest_observables` would return it.
OBSERVABLES = {"dout", "rst_n", "sclk", "status_reg", "vout", "ldo"}

# --- the two families, in the shape the input actually writes them ----------
DISCLOSURE = ("Tool disclosure: the open PDK ships sectioned corner libraries "
              "for every device class; corner sims bind those sections "
              "directly. Results are SIMULATED, not silicon sign-off.")
ORACLE_NOTE = ("Golden cross-check (verify stage only): the fabricated part's "
               "layout plus its extracted netlist, compared at chip level.")

# --- sentences that MUST stay rows -----------------------------------------
KEEPERS = [
    "Drive rst_n low for 10 cycles and check dout == 0x00.",
    "Apply a 1 kHz full-scale sine to the input; SNDR >= 60 dB.",
    "Sweep the vout load from 0 to 10 mA; regulation within 2 %.",
    "Multi-corner: TT/SS/FF over the declared -40/27/125 C set.",
    "status_reg reads back the last written value.",
    "Load regulation better than 50 ppm.",
    "SFDR at least -70 dBc.",
    # The conjunction, both halves alone: a comparison that names no oracle,
    # and an oracle-role noun with no comparison.  Neither is a cross-check.
    "Compare the measured settling time against the declared 5 us limit.",
    "Minimum sign-off matrix: 9 process corners over 3 temperatures, 125 C.",
    # The four bullets of this repo's own #634 converter fixture, verbatim.
    "DC operating-point check across the analog front-end (bias, common-mode).",
    "Line and load regulation of the on-chip LDO over the supply range.",
    "SNDR / ENOB transient with an input sine sweep at multiple amplitudes.",
    "Multi-corner (TT/SS/FF, temperature) re-simulation of the modulator.",
]


# ---------------------------------------------------------------------------
# 1. the two refusal families
# ---------------------------------------------------------------------------
def test_golden_cross_check_is_refused_and_names_4_05():
    """The oracle cross-check is REFUSED, and the reason names §4.05."""
    became_row, refusal = _verdict(ORACLE_NOTE)
    assert not became_row, (
        "the golden cross-check is a functional-test row — §4.05 forbids "
        "reading the oracle at design time, so it can never be one")
    assert refusal is not None, "it was dropped without a recorded reason"
    assert refusal["reason_code"] == "ORACLE_CROSS_CHECK_4_05"
    assert "4.05" in refusal["reason"], (
        "the refusal must NAME the rule it applies, not merely apply it: "
        f"{refusal['reason']!r}")


def test_tool_disclosure_is_refused_and_names_its_label():
    """A disclosure declares its own documentation role in its label."""
    became_row, refusal = _verdict(DISCLOSURE)
    assert not became_row, "the tool disclosure is a functional-test row"
    assert refusal is not None, "it was dropped without a recorded reason"
    assert refusal["reason_code"] == "DISCLOSURE_OR_METHOD_NOTE"
    assert "disclosure" in refusal["reason"].lower()


@pytest.mark.parametrize("label", [
    "Note", "Caveat", "Methodology", "Assumption", "Limitation", "Errata",
    "Convention", "Rationale",
])
def test_every_documentation_role_label_is_refused(label):
    """The family is a documentation-role VOCABULARY, not one literal."""
    became_row, refusal = _verdict(
        f"{label}: the deck binds every corner section directly at 10 ns.")
    assert not became_row and refusal is not None
    assert refusal["reason_code"] == "DISCLOSURE_OR_METHOD_NOTE"


def test_a_sentence_is_never_refused_merely_for_being_unrecognised():
    """POSITIVE EVIDENCE ONLY — absence of an anchor is not a refusal.

    Round 1 of this fix refused a bullet whose text carried no literal, no
    relation and no name from the design's own L-docs. It found nothing on the
    corpus and it deleted two GENUINE analog acceptances from this repo's own
    #634 converter fixture — which then failed the L10 floor at 1 case, the
    same wall this fix exists to move, one layer earlier. The arm below is the
    guard against that rule ever coming back.
    """
    for sentence in (
            "corner sweep over the declared process/temperature set",
            "DC operating-point check across the analog front-end (bias).",
            "SNDR / ENOB transient with an input sine sweep at amplitudes."):
        became_row, refusal = _verdict(sentence)
        assert became_row, (
            f"an unrecognised — not a disclosure, not a cross-check — "
            f"sentence was refused ({refusal!r}): {sentence!r}")


# ---------------------------------------------------------------------------
# 2. the no-leak arms — the refusal must not swallow a real acceptance
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sentence", KEEPERS)
def test_a_real_acceptance_sentence_is_still_a_row(sentence):
    """PASSES ON BOTH TREES — that is the point: nothing real was lost."""
    became_row, refusal = _verdict(sentence)
    assert became_row, (
        f"a genuine acceptance sentence stopped being an L10 row "
        f"({refusal!r}): {sentence!r}")


def test_the_oracle_refusal_needs_BOTH_halves():
    """A comparison verb alone, or an oracle noun alone, is not a cross-check.

    This is the arm that keeps the §4.05 family from becoming a word filter:
    an analog spec says "golden ratio" and "compare against the limit" without
    ever naming an oracle to read.
    """
    compare_only = "Cross-check the two counters against each other at 100 ns."
    oracle_only = "Golden ratio scaling of the mirror legs is 4.0 ratio; dout."
    assert _verdict(compare_only)[0], compare_only
    assert _verdict(oracle_only)[0], oracle_only


# ---------------------------------------------------------------------------
# 3. end to end through the real extractor
# ---------------------------------------------------------------------------
def test_extractor_emits_the_acceptances_and_refuses_the_other_two():
    """The measured u_hawaii_adc shape: 4 bullets in, 2 rows out, 2 recorded."""
    acceptance_a = "Apply a 1 kHz full-scale sine to the input; SNDR >= 60 dB."
    acceptance_b = "Multi-corner: TT/SS/FF over the declared -40/27/125 C set."
    doc = _run_l10([acceptance_a, acceptance_b, DISCLOSURE, ORACLE_NOTE])

    stimuli = [c.get("stimulus") for c in doc["test_cases"]]
    assert stimuli == [acceptance_a, acceptance_b], (
        "MEMBERSHIP, not count: the surviving rows must be exactly the two "
        f"acceptances, in order — got {stimuli!r}")
    for case in doc["test_cases"]:
        assert case["kind"] == "verification_intent"

    refusals = doc["verification_intent_refusals"]
    assert len(refusals) == 2
    by_code = {r["reason_code"]: r for r in refusals}
    assert set(by_code) == {"DISCLOSURE_OR_METHOD_NOTE",
                            "ORACLE_CROSS_CHECK_4_05"}
    # NEVER SILENTLY DROPPED: the record carries the sentence itself, so a
    # reader can see what the input declared and why it is not a test.
    assert by_code["ORACLE_CROSS_CHECK_4_05"]["sentence"].startswith(
        "Golden cross-check")
    assert "4.05" in by_code["ORACLE_CROSS_CHECK_4_05"]["reason"]
    assert by_code["DISCLOSURE_OR_METHOD_NOTE"]["sentence"].startswith(
        "Tool disclosure")
    for refusal in refusals:
        assert refusal["evidence"], "a refusal must cite the doc it came from"


def test_the_refusal_record_is_published_even_when_nothing_was_refused():
    """"Nothing was declared" and "something dropped it" must not collapse."""
    doc = _run_l10(["Apply a 1 kHz sine to the input; SNDR >= 60 dB.",
                    "Sweep the vout load from 0 to 10 mA; regulation 2 %."])
    assert doc["verification_intent_refusals"] == []
    assert "verification_intent_refusals" in doc, (
        "the key must be PRESENT and empty, not absent: absent is "
        "indistinguishable from a tree that never had the refusal at all")
    assert len(doc["test_cases"]) == 2


def test_a_kept_row_is_byte_identical_to_what_the_extractor_emitted_before():
    """The refusal narrows the population; it must not rewrite a survivor.

    The pre-#2055 emitter wrote exactly these five keys with a constant
    `expected`.  A survivor must still carry them unchanged, so the corpus
    control (`membership + content, base vs head`) compares like with like.
    """
    sentence = "Apply a 1 kHz full-scale sine to the input; SNDR >= 60 dB."
    doc = _run_l10([sentence, DISCLOSURE])
    row = doc["test_cases"][0]
    assert row == {
        "name": "apply_a_1_khz_full_scale_sine_to_the_input_sndr_",
        "kind": "verification_intent",
        "stimulus": sentence,
        "expected": ("verification intent satisfied "
                     "(analog/mixed-signal acceptance check)"),
        "evidence": ("input/docs/L5_ANALOG_SPEC.md "
                     "(Verification intent section)"),
    }


def test_the_L7_intent_harvest_is_untouched():
    """The sentence is still verification INTENT; it is just not a test CASE.

    L7 is where intent belongs, and it reads the SAME helper.  If the refusal
    had been pushed down into `_v634_harvest_verification_intent` the input's
    disclosure would have vanished from the design record entirely.
    """
    harvested = P._v634_harvest_verification_intent(
        {"L5_ANALOG_SPEC.md": _l5_doc([DISCLOSURE, ORACLE_NOTE])})
    assert len(harvested) == 2, (
        "the shared harvester must still return every bullet — only the L10 "
        "promotion refuses them")


# ---------------------------------------------------------------------------
# 4. Step 4 names the row kind it could not run
# ---------------------------------------------------------------------------
def _step4_project(rows):
    root = Path(tempfile.mkdtemp(prefix="i2055_s4_"))
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": rows}))
    return root


def _disclosure(project) -> str:
    """`_row_kind_disclosure`, or "" on a tree that has no such sentence.

    getattr, not a direct call: on the pre-fix tree this returns the empty
    string and every arm below fails on WHAT THE SENTENCE SAYS, which is the
    defect, instead of on an AttributeError, which is not."""
    fn = getattr(C, "_row_kind_disclosure", None)
    return fn(project) if callable(fn) else ""


def test_step4_disclosure_names_the_kind_and_the_authorable_count():
    rows = [{"name": f"vi{i}", "kind": "verification_intent"} for i in range(4)]
    text = _disclosure(_step4_project(rows))
    assert "verification_intent 4" in text, text
    assert "0 of 4 row(s)" in text, text
    # The producer's scope is IMPORTED, not respelled — so the sentence and the
    # producer can never disagree about which kinds are authorable.
    for kind in TB.SCAFFOLD_KINDS:
        assert kind in text


def test_step4_disclosure_counts_an_authorable_row_as_authorable():
    """The new sentence must not read "0 authorable" over a real vector."""
    rows = [{"name": "vi", "kind": "verification_intent"},
            {"name": "kav", "kind": "known_answer_vector"}]
    text = _disclosure(_step4_project(rows))
    assert "1 of 2 row(s)" in text, text


def test_step4_disclosure_is_empty_when_it_could_not_read_the_rows():
    """"Could not read it" is not "read it and it was empty"."""
    root = Path(tempfile.mkdtemp(prefix="i2055_s4_none_"))
    (root / "phase1" / "generated_docs").mkdir(parents=True)
    assert _disclosure(root) == ""
    denom = getattr(C, "_row_kind_denominator", lambda _p: {})(root)
    assert denom.get("declared_row_kinds", {}) == {}


def test_step4_denominator_publishes_the_same_two_facts():
    rows = [{"name": "vi", "kind": "verification_intent"}]
    denom = getattr(C, "_row_kind_denominator", lambda _p: {})(
        _step4_project(rows))
    assert denom["declared_row_kinds"] == {"verification_intent": 1}
    assert denom["rows_inside_tb_producer_scaffold_scope"] == 0
    assert denom["tb_producer_scaffold_scope"] == sorted(TB.SCAFFOLD_KINDS)


# ---------------------------------------------------------------------------
# 5. the oracle CELL's polarity is asked before the cell is believed
#
# `prose_polarity_consulted_check` named
# `phase1_doc_one_shot_runner::_harvest_test_cases_from_input_tables` from
# v1.17.79: it reads a value out of a verification-plan table cell and writes it
# into `expected` as a declaration without asking whether that cell DENIES the
# proposition it is about — the #706 `pdk_target` / #711 `die_area_budget_um`
# shape one layer over.
#
# The instance is the ASSERTION ROW. `_L10_TC_AFFIRM_LED` is a one-sided
# vocabulary: it knows the word that says YES and nothing that says NO, so a
# cell reading `OK - not required for this revision` was affirmation-led, had no
# digit and no relation in its tail, and was published as `holds: <scenario>` —
# the design's own table saying NOT REQUIRED and L10 declaring it must hold.
# ---------------------------------------------------------------------------
def _table(rows) -> str:
    body = "\n".join(f"| {a} | {b} |" for a, b in rows)
    return "| scenario | expected |\n|---|---|\n" + body + "\n"


def _harvest(rows):
    """{name-prefix: case} for one `| scenario | expected |` table."""
    cases = P._harvest_test_cases_from_input_tables({"L7_TEST_DEBUG.md":
                                                     _table(rows)})
    return {c["stimulus"]: c for c in cases}


def test_an_affirmation_that_also_denies_is_not_an_affirmation():
    """THE DEFECT. The cell says NOT REQUIRED; nothing may declare it holds."""
    scenario = "the core stays in reset while cfg_en is low"
    cell = "OK - not required for this revision"
    case = _harvest([(scenario, cell)])[scenario]
    assert case["expected"] != f"holds: {scenario}", (
        "a cell that affirms AND denies was published as an affirmation — the "
        "polarity of the sentence was never asked")
    assert case["expected"] == cell, (
        "when a cell both affirms and denies, the conservative half is to keep "
        "it verbatim and let the oracle-anchor gate judge it")
    assert "oracle_from_assertion_row" not in case


def test_a_plain_affirmation_row_is_byte_identical():
    """NO-LEAK. The affirmation branch is unchanged where nothing denies."""
    scenario = "the core stays in reset while cfg_en is low"
    case = _harvest([(scenario, "OK")])[scenario]
    assert case["expected"] == f"holds: {scenario}"
    assert case["oracle_from_assertion_row"] is True
    assert case["assertion_affirmation"] == "OK"


def test_a_substantive_oracle_carrying_a_denial_word_survives_untouched():
    """NO-LEAK, and the bound that makes the denial branches safe.

    `expected = "no response frame"` is a perfectly good golden value that
    happens to contain "no".  Rewriting it would destroy a real oracle, so a
    denial verdict is returned only when the cell is NOTHING BUT the denial.
    """
    scenario = "the bus goes silent on a bad address"
    case = _harvest([(scenario, "no response frame")])[scenario]
    assert case["expected"] == "no response frame"
    assert "oracle_from_denial_row" not in case
    assert "oracle_retired_by_input" not in case


@pytest.mark.parametrize("cell", ["No", "not", "否"])
def test_a_bare_CORE_denial_states_a_predicate(cell):
    """A stated NO becomes something a testbench can check, not a bare marker."""
    scenario = "the fifo overflows on the 9th write"
    case = _harvest([(scenario, cell)])[scenario]
    assert case["expected"] == f"does not hold: {scenario}"
    assert case["oracle_from_denial_row"] is True
    # A refusal that names its evidence is checkable; a bare flag is not.
    assert case["denial_word"] == cell


@pytest.mark.parametrize("cell", ["N/A", "superseded", "deprecated"])
def test_a_RETIRED_denial_is_marked_not_graded(cell):
    """The two tiers are NOT interchangeable.

    "n/a" says the row DOES NOT APPLY.  That is not a false proposition and
    must not be emitted as one — emitting `does not hold:` here would fabricate
    a requirement the input never stated.
    """
    scenario = "the legacy wake pulse is honoured"
    case = _harvest([(scenario, cell)])[scenario]
    assert case["expected"] == cell, "a retired row keeps its cell verbatim"
    assert case["oracle_retired_by_input"] is True
    assert "oracle_from_denial_row" not in case


def test_the_gate_no_longer_names_this_function():
    """`prose_polarity_consulted_check` must not name it — and must have LOOKED.

    A zero from an instrument that scanned nothing is not a pass, so the run is
    required to have found a real population first.
    """
    import subprocess
    plugin = _PROGRAMS.parent
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "prose_polarity_consulted_check.py"),
         "--root", str(plugin)],
        capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    assert "CANNOT DETERMINE" not in out, (
        f"the gate could not scan; that is NOT_MEASURED, not a pass: {out[:400]}")
    assert "polarity-blind" in out or "prose extractor" in out, (
        f"the gate produced no population to judge: {out[:400]}")
    assert "_harvest_test_cases_from_input_tables" not in out, (
        "the offender is still named by the gate:\n"
        + "\n".join(l for l in out.splitlines() if "::" in l)[:800])


def test_the_function_is_clean_by_CONSULTING_not_by_EXEMPTION():
    """It must go to zero, not into a register.

    Neither the accepted-debt baseline nor the `_NOT_PROSE` exempt set may
    name it: both would record the debt rather than pay it.
    """
    import prose_polarity_consulted_check as G  # noqa: WPS433
    name = "phase1_doc_one_shot_runner::_harvest_test_cases_from_input_tables"
    assert name not in G._NOT_PROSE, (
        "the function was exempted as NOT PROSE — it reads hand-written "
        "verification-plan prose, in which 'not' is spellable and was spelled")
    baseline = json.loads(
        (_PROGRAMS / G._BASELINE_NAME).read_text(errors="replace"))
    entries = baseline.get("polarity_blind", baseline) if isinstance(
        baseline, dict) else baseline
    assert entries, (
        "the baseline could not be read as a population — NOT_MEASURED, not a "
        "pass")
    assert name not in entries, (
        "the function was recorded as accepted debt in "
        f"{G._BASELINE_NAME} instead of being fixed")


# ---------------------------------------------------------------------------
# 6. ONE place writes L1.tapeout_metadata.top_cell   (#2060 item 3)
#
# The mirror was copied into THREE of the branches that resolve `top_module`
# and absent from the other three — and the three without it are the
# HIGHER-priority ones, so the better the evidence the more likely the field
# vanished.  MEASURED over 25 485 published L9 documents on the lane host:
#
#     l1_ic_name_fallback             14044 docs      0 carry top_cell
#     canonical_chip_top_sentinel      2431 docs      0 carry top_cell
#     doc_module_decl_or_heading       1040 docs      0 carry top_cell
#     doc_prose_top_module_v1_6_409     102 docs    102 carry top_cell  (100%)
#     rtl_top_prose_v1_6_545             10 docs      0 carry top_cell
#     staged_rtl_structural_top           4 docs      0 carry top_cell
#
# Three mirror SITES existed; exactly ONE of them ever produced the field.  So
# for the IC whose top moved from a prose-walker win to a stated-top win, the
# field disappeared and nothing went red.
# ---------------------------------------------------------------------------
def _l1_project(ic_name: str = "probe_ic"):
    root = Path(tempfile.mkdtemp(prefix="i2060_"))
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(
        {"ic_name": ic_name, "schema_version": 2, "doc_class": "datasheet"}))
    return root


def _top_cell_of(root: Path):
    l1 = json.loads((root / "phase1" / "generated_docs" / "L1_DATASHEET.json")
                    .read_text(errors="replace"))
    return (l1.get("tapeout_metadata") or {}).get("top_cell")


def _run_l9(docs, ic_name="probe_ic"):
    root = _l1_project(ic_name)
    (root / "input" / "docs").mkdir(parents=True)
    for fname, text in docs.items():
        (root / "input" / "docs" / fname).write_text(text)
    P.gen_l9_integration_spec(root, dict(docs), {})
    l9 = json.loads((root / "phase1" / "generated_docs" /
                     "L9_INTEGRATION_SPEC.json").read_text(errors="replace"))
    f = l9.get("fields", l9)
    return f.get("top_module_extraction_strategy"), _top_cell_of(root)


def _design_owned_strategies():
    """The roster, DERIVED from the tree — never a list retyped here."""
    try:
        import _pack_top_module as _ptm  # noqa: WPS433
        return set(_ptm.DESIGN_OWNED_STRATEGIES)
    except Exception:
        return set(P._DESIGN_OWNED_TOP_STRATEGIES_FALLBACK)


def test_every_branch_that_publishes_a_declared_top_writes_the_top_cell():
    """The unification, enumerated from the tree rather than from memory.

    A branch added later is covered the day it is added: the mirror is keyed on
    the STATUS the cascade already computes, not on a list of strategy names
    that someone has to remember to extend.
    """
    owned = _design_owned_strategies()
    assert owned, "the design-owned roster could not be read — NOT_MEASURED"
    for strategy in sorted(owned):
        status = P._top_module_status_for(strategy)
        assert status == P.TOP_MODULE_STATUS_DECLARED, (
            f"{strategy} is design-owned but its status is {status!r}")
        root = _l1_project()
        assert P._v2060_mirror_top_cell(root, "adc_core", status) is True, (
            f"the branch {strategy} publishes a declared top and did not "
            f"write L1.tapeout_metadata.top_cell")
        assert _top_cell_of(root) == "adc_core"


def test_the_walker_branch_is_byte_identical():
    """THE NAMED CONTROL. The one branch that already mirrored must not move.

    102 of 102 published L9 documents resolved by `doc_prose_top_module_v1_6_409`
    carry `tapeout_metadata.top_cell`; that must still be true, with the same
    value, written the same way.
    """
    status = P._top_module_status_for("doc_prose_top_module_v1_6_409")
    root = _l1_project()
    assert P._v2060_mirror_top_cell(root, "adc_core", status) is True
    l1 = json.loads((root / "phase1" / "generated_docs" / "L1_DATASHEET.json")
                    .read_text(errors="replace"))
    assert l1["tapeout_metadata"]["top_cell"] == "adc_core"
    assert l1["no_tapeout_metadata_in_input"] is False


def test_a_stated_top_now_carries_the_field_end_to_end():
    """THE DEFECT, through the real cascade.

    `doc_module_decl_or_heading` is the highest-priority document branch and
    the largest observed population (1040 L9 docs, 0 with the field).
    """
    strategy, top_cell = _run_l9(
        {"README.md": "# Design\n\nmodule adc_core (input clk);\nendmodule\n"})
    assert strategy == "doc_module_decl_or_heading", strategy
    assert top_cell == "adc_core", (
        "a design whose own document declares its top module published no top "
        "cell of record")


def test_a_design_with_no_declared_top_writes_nothing_end_to_end():
    strategy, top_cell = _run_l9(
        {"README.md": "# Design\n\nA converter with no declared top.\n"})
    assert strategy == P.TOP_MODULE_UNDECLARED_STRATEGY, strategy
    assert top_cell is None


@pytest.mark.parametrize("strategy", [
    "l1_ic_name_fallback", "canonical_chip_top_sentinel", "top_undeclared",
    "some_strategy_nobody_classified",
])
def test_a_name_the_flow_derived_is_never_a_tapeout_fact(strategy):
    """The safety argument, and the reason this is not simply "always write it".

    `tapeout_metadata.top_cell` is the top cell OF RECORD.  A label the flow
    DERIVED from the chip's identifier is not one, and a design that declared
    no top certainly is not — writing either would publish a fabricated
    tape-out fact, which is what #2049 and #2052 were just spent removing from
    this same cascade.  14 044 + 2 431 published L9 documents sit on those two
    statuses.
    """
    status = P._top_module_status_for(strategy)
    assert status != P.TOP_MODULE_STATUS_DECLARED
    root = _l1_project()
    assert P._v2060_mirror_top_cell(root, "adc_core", status) is False
    assert _top_cell_of(root) is None


def test_the_mirror_declines_loudly_rather_than_raising():
    """"Could not" and "declined" are different, and neither may take L9 down."""
    missing = Path(tempfile.mkdtemp(prefix="i2060_none_"))
    assert P._v2060_mirror_top_cell(
        missing, "adc_core", P.TOP_MODULE_STATUS_DECLARED) is False
    bad = _l1_project()
    (bad / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text("{[")
    assert P._v2060_mirror_top_cell(
        bad, "adc_core", P.TOP_MODULE_STATUS_DECLARED) is False
    empty = _l1_project()
    assert P._v2060_mirror_top_cell(
        empty, "", P.TOP_MODULE_STATUS_DECLARED) is False


def test_there_is_exactly_ONE_writer_of_the_field_in_this_module():
    """ONE PLACE, enforced — so a fourth private copy cannot appear quietly.

    Parsed, not grepped: a comment or a docstring mentioning the field is not a
    writer, and the point of the fix is that only one statement assigns it.
    """
    import ast as _ast
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(
        errors="replace")
    tree = _ast.parse(src)
    writers = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Subscript)
        and isinstance(n.slice, _ast.Constant)
        and n.slice.value == "top_cell"
        and isinstance(getattr(n, "ctx", None), _ast.Store)
    ]
    assert len(writers) == 1, (
        f"{len(writers)} statements assign tapeout_metadata['top_cell'] at "
        f"lines {[w.lineno for w in writers]} — the mirror was copied again")


def test_the_l9_generator_departure_is_a_scope_artefact_not_a_fix():
    """It left the polarity-blind register WITHOUT learning anything.

    Extracting the top-cell writes into `_v2060_mirror_top_cell` moved
    `gen_l9_integration_spec` out of `prose_polarity_consulted_check`'s
    population, because `_writes_a_declared_value` asks whether a subscript
    assignment writes a value that is match-derived IN THE SAME FUNCTION and
    the name now arrives as a parameter.  That is a scope artefact, not a
    tightening, and this arm exists so it can never be recorded as one: the
    function still reads prose and still never asks whether the sentence
    denies the top it just read.
    """
    import ast as _ast
    import prose_polarity_consulted_check as G  # noqa: WPS433
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(
        errors="replace")
    tree = _ast.parse(src)
    aliases = G._aliases(tree)
    fns = {n.name: n for n in _ast.walk(tree)
           if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
    l9 = fns["gen_l9_integration_spec"]
    assert G._searches_prose(l9) is True, (
        "the fixture is invalid: the generator no longer reads prose at all, "
        "so this arm is about nothing")
    assert G._consults_polarity(l9, aliases) is False, (
        "gen_l9_integration_spec now consults polarity — that IS a fix, and "
        "this arm must be replaced by one that pins the fix instead of the "
        "honest disclosure of a scope artefact")
    mirror = fns["_v2060_mirror_top_cell"]
    assert G._searches_prose(mirror) is False, (
        "the mirror reads a sentence — then it owes a polarity consult like "
        "any other prose extractor")


# ---------------------------------------------------------------------------
# 7. a record says whether it carries a port table   (#2060, HUNK B)
#
# `_PORT_TABLE_STRATEGIES` is an allow-list keyed on a NAME, and the failure
# when a new extractor is not added to it is SILENT: form 2 of
# `_pin_has_port_like_evidence` does not fire, the pin fails corroboration, and
# the L1.pin_table -> L9 promoter drops a real port with no diagnostic.  Lane
# czport's #2060 work adds two port-table extractors that mint their own
# strategy strings; neither can be in a frozenset written before they existed.
# ---------------------------------------------------------------------------
def _port_table_names():
    """The legacy roster, read from the module — never retyped here."""
    return sorted(P._PORT_TABLE_STRATEGIES)


@pytest.mark.parametrize("flag", list(P._V2060_PORT_TABLE_FLAG_KEYS))
def test_a_record_that_declares_a_port_table_is_corroborated_by_its_flag(flag):
    """THE RULING. A strategy name nobody has ever seen, plus the record's own
    declaration, is enough — that is the point: no second file to remember."""
    pin = {"name": "sig9", "extraction_strategy": "an_extractor_written_later",
           flag: True}
    assert P._v2060_record_declares_a_port_table(pin) is True
    assert P._pin_has_port_like_evidence(pin) is True


def test_a_new_extractors_ports_are_dropped_without_the_flag_or_the_list():
    """THE DEFECT, stated as a fact about the mechanism.

    A record from an extractor that is in neither the roster nor flagged, whose
    name carries no direction affix and no conventional stem, fails
    corroboration — which is exactly what happens to a new port-table extractor
    that the allow-list has never heard of.
    """
    pin = {"name": "sig9", "extraction_strategy": "an_extractor_written_later"}
    assert P._v2060_record_declares_a_port_table(pin) is False
    assert P._pin_has_port_like_evidence(pin) is False


@pytest.mark.parametrize("strategy", _port_table_names())
def test_every_legacy_roster_entry_is_still_corroborated(strategy):
    """NO-LEAK, over the FULL roster rather than a sample.

    The flag is added ahead of the list, never in place of it: this change can
    only stop dropping ports it should never have dropped.
    """
    for key in ("extraction_strategy", "_extraction"):
        assert P._v2060_record_declares_a_port_table(
            {"name": "sig9", key: strategy}) is True, (key, strategy)


@pytest.mark.parametrize("strategy", _port_table_names()[:4])
def test_an_annotated_strategy_keeps_its_provenance(strategy):
    """The `+<annotation>` form (#664) must survive, at BOTH call sites."""
    annotated = f"{strategy}+width_parametric_v1_6_423"
    assert P._v2060_record_declares_a_port_table(
        {"name": "sig9", "_extraction": annotated}) is True


def test_a_record_with_no_provenance_at_all_is_not_corroborated():
    assert P._v2060_record_declares_a_port_table({}) is False
    assert P._v2060_record_declares_a_port_table(None) is False
    assert P._v2060_record_declares_a_port_table(
        {"name": "sig9", "extraction_strategy": ""}) is False
    # A FALSE flag is a declaration too, and it declares the opposite.
    assert P._v2060_record_declares_a_port_table(
        {"name": "sig9", "from_port_table": False}) is False


def test_both_call_sites_ask_the_same_predicate():
    """Two private spellings of one question is how the first one drifted.

    Parsed, not grepped: every site that tests port-table provenance must go
    through the one predicate, so `_PORT_TABLE_STRATEGIES` is no longer read
    directly by a decision.
    """
    import ast as _ast
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(
        errors="replace")
    tree = _ast.parse(src)
    readers = [
        n.lineno for n in _ast.walk(tree)
        if isinstance(n, _ast.Compare)
        and any(isinstance(op, _ast.In) for op in n.ops)
        and any(isinstance(c, _ast.Name)
                and c.id == "_PORT_TABLE_STRATEGIES" for c in n.comparators)
    ]
    inside = [
        n for n in _ast.walk(tree)
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
        and n.name == "_v2060_record_declares_a_port_table"
    ]
    assert len(inside) == 1
    lo, hi = inside[0].lineno, max(
        getattr(x, "lineno", inside[0].lineno) for x in _ast.walk(inside[0]))
    stray = [ln for ln in readers if not (lo <= ln <= hi)]
    assert not stray, (
        f"`_PORT_TABLE_STRATEGIES` is still consulted directly at lines "
        f"{stray} — the name list is a fallback INSIDE the predicate, not a "
        f"contract other code reads")


@pytest.mark.parametrize("strategy", [
    # The two strategies lane czport's #2060 work mints. Named here as DATA the
    # predicate must handle, not as a list the predicate reads: the point is
    # that neither had to be entered anywhere for its ports to be corroborated.
    "verilog_code_region_port_decl_issue2060",
    "markdown_signal_table_port_row_issue2060",
    # and the shape generally
    "some_future_signal_table_row_reader",
    "whatever_pin_table_walker_v9",
])
def test_a_strategy_that_declares_its_own_shape_needs_no_allow_list(strategy):
    """HUNK A, made land-ready without carrying another lane's unlanded file.

    `extract_code_block_ports` and both strategy constants live only on
    `next/czport` and cannot be imported here, so HUNK A itself is not
    applicable on this base.  What CAN be done today — and is the ruling's whole
    point — is to remove the coupling that made HUNK A dangerous without HUNK B:
    a strategy whose name says it read a port declaration or a port/signal/pin
    table has stated the fact, and is corroborated by shape.
    """
    pin = {"name": "sig9", "extraction_strategy": strategy}
    assert P._v2060_record_declares_a_port_table(pin) is True
    assert P._pin_has_port_like_evidence(pin) is True


@pytest.mark.parametrize("strategy", [
    "an_extractor_written_later", "sdc_directive_scan",
    "stdcell_library_shape", "narrative_prose_walk",
])
def test_the_shape_rule_does_not_admit_a_non_port_strategy(strategy):
    """NO-LEAK.  It is a SHAPE, not "anything with an underscore"."""
    assert P._v2060_record_declares_a_port_table(
        {"name": "sig9", "extraction_strategy": strategy}) is False
def _decl_gate():
    import hdl_declaration_scan_strips_comments_check as G  # noqa: WPS433
    return G


def test_the_oracle_vocabulary_does_not_read_as_an_hdl_declaration():
    G = _decl_gate()
    assert G.declares_hdl(P._V2055_ORACLE_ARTEFACT_RE.pattern) is False, (
        "the oracle-artefact vocabulary names an HDL declaration keyword; a "
        "scan of it over unstripped text is a real finding, and the fix is to "
        "drop the token, never to exempt the site")
    # The instrument can see: the SAME predicate says True for a pattern that
    # really does name one.  A detector that cannot fire proves nothing.
    assert G.declares_hdl(r"\bmodule\s+(\w+)") is True


def test_dropping_the_token_cost_no_verdict():
    """The swap was measured, not assumed.

    `reference output` / `expected output file` went; `reference result(s) /
    vector(s)` and `expected answer file` say the same thing.  Every sentence
    this lane measured keeps its verdict.
    """
    refused = [
        "Golden cross-check (verify stage only): the fabricated part's layout.",
        "Golden cross-check: compare the netlist against the fabricated part.",
        "Verify against the golden reference output committed under tests/.",
    ]
    for sentence in refused:
        became_row, refusal = _verdict(sentence)
        assert not became_row and refusal is not None, sentence
        assert refusal["reason_code"] == "ORACLE_CROSS_CHECK_4_05", sentence
    for sentence in (
            "Compare the measured settling time against the declared 5 us limit.",
            "Cross-check the two counters against each other after 100 cycles."):
        assert _verdict(sentence)[0], sentence


def test_the_declaration_scan_does_not_name_this_lanes_regex():
    """It went to ZERO by not writing the token — not into either register.

    Checked three ways, because a green from a scan that looked at nothing is
    not a green: the run must produce a real population, the function must be
    absent from the raw findings, and it must be absent from BOTH the accepted-
    debt baseline and the gate's non-HDL exemption map.
    """
    import json as _json
    import subprocess
    G = _decl_gate()
    plugin = _PROGRAMS.parent
    out_json = Path(tempfile.mkdtemp(prefix="i2055_hdl_")) / "scan.json"
    subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "hdl_declaration_scan_strips_comments_check.py"),
         "--root", str(plugin), "--json", str(out_json)],
        capture_output=True, text=True, timeout=1800)
    assert out_json.is_file(), "the scan wrote no report — NOT_MEASURED"
    report = _json.loads(out_json.read_text(errors="replace"))
    raw = report.get("unstripped_scans") or []
    assert len(raw) > 50, (
        f"the scan found {len(raw)} call sites — that is not a population this "
        f"tree can have, so the run measured nothing")
    mine = [r for r in raw if "_V2055_ORACLE_ARTEFACT_RE" in r]
    assert mine == [], f"still named by the gate: {mine}"
    baseline = _json.loads(
        (_PROGRAMS / "hdl_declaration_scan_baseline.json").read_text(
            errors="replace"))
    known = baseline.get("known") or []
    assert known, "the baseline could not be read as a population"
    assert not [k for k in known if "_V2055" in k], (
        "the finding was recorded as accepted debt instead of removed")
    assert not [k for k in G._NOT_HDL_DECLARATION if "_V2055" in k], (
        "the finding was exempted as non-HDL instead of removed")


# ---------------------------------------------------------------------------
# 9. HUNK A — the docs door reads a code-block / signal-table port list
#
# `phase1_port_extract.extract_code_block_ports` landed with czport (v1.18.1)
# carrying NO production call site — only tests.  This is that caller for the
# docs door, and it is the half that is unsafe without HUNK B: every entry
# carries `CODE_REGION_PORT_STRATEGY` / `SIGNAL_TABLE_PORT_STRATEGY`, neither of
# which is in `_PORT_TABLE_STRATEGIES`, so `_pin_has_port_like_evidence` would
# refuse them and the L1.pin_table -> L9.top_ports promoter would drop them.
#
# MEASURED, base `dc12d3465` (v1.18.1, extractor present but not wired) vs this
# branch, over 60 staged prompt-entry design inputs:
#     ports 203 -> 273 (+70), zero-port 36 -> 28, LOST 0 by membership.
# ---------------------------------------------------------------------------
def _pins_of(text):
    root = Path(tempfile.mkdtemp(prefix="i2060_a_"))
    (root / "phase1" / "generated_docs").mkdir(parents=True)
    (root / "input" / "docs").mkdir(parents=True)
    (root / "input" / "docs" / "SPEC.md").write_text(text)
    P.gen_l1_datasheet(root, {"SPEC.md": text})
    l1 = json.loads((root / "phase1" / "generated_docs" / "L1_DATASHEET.json")
                    .read_text(errors="replace"))
    f = l1.get("fields", l1)
    return sorted({str(p.get("name") or "").strip()
                   for p in (f.get("pin_table") or [])
                   if isinstance(p, dict) and str(p.get("name") or "").strip()})


_CODE_BLOCK = (
    "# binary to BCD\n\nThe module converts a binary value.\n\n"
    "```verilog\nmodule binary_to_BCD (\n"
    "  input  logic [7:0] binary_in,   // 8-bit binary input\n"
    "  input  logic       clk,\n"
    "  output logic [3:0] bcd_ones,\n"
    "  output logic       done\n"
    ");\nendmodule\n```\n")


def test_a_port_declared_only_in_a_code_block_reaches_the_pin_table():
    """THE WITNESS czport named: `input logic [7:0] binary_in,  // ...`.

    Measured on the base tree the other harvesters already find the rest of
    that header; `binary_in` — the one carrying a trailing comment after the
    comma — is the port HUNK A adds.
    """
    pins = _pins_of(_CODE_BLOCK)
    assert "binary_in" in pins, (
        f"the port declared in the ```verilog fence never reached the pin "
        f"table: {pins}")
    for other in ("clk", "bcd_ones", "done"):
        assert other in pins, (other, pins)


def test_a_signal_table_with_a_direction_column_reaches_the_pin_table():
    pins = _pins_of(
        "# spec\n\n| Signal | Direction | Width | Description |\n|---|---|---|---|\n"
        "| data_in | input | 8 | payload |\n| result | output | 8 | out |\n")
    assert {"data_in", "result"} <= set(pins), pins


@pytest.mark.parametrize("text,why", [
    ("# lint review\n\nPlease review this module for area. It should be\n"
     "optimised; see the report.\nendmodule is mentioned in prose.\n",
     "a prose sentence saying 'module' is not a port list"),
    ("# timing\n\n| Clock Cycle | clk | rst_n | data_in |\n|---|---|---|---|\n"
     "| 0 | 0 | 1 | 8'h00 |\n",
     "a waveform table has no DIRECTION column"),
])
def test_hunk_A_invents_no_port(text, why):
    """NO-LEAK.  The grammar refuses what it should refuse — and this is the
    arm that matters, because the whole change is ADDITIVE: it can only add
    ports, so what it adds must be real."""
    assert _pins_of(text) == [], why


def test_the_code_block_ports_are_corroborated_by_HUNK_B():
    """A and B are one change.  Without B these ports are dropped in silence.

    Asserted through the corroboration predicate itself over the real
    extractor's real output, not over a hand-written strategy string.
    """
    import phase1_port_extract as _ppx  # noqa: WPS433
    entries = _ppx.extract_code_block_ports(_CODE_BLOCK)
    assert entries, "the extractor returned nothing — the fixture is invalid"
    for entry in entries:
        strategy = entry.get("extraction_strategy")
        assert strategy, entry
        # the record as HUNK A stores it
        assert P._v2060_record_declares_a_port_table(
            {**entry, "from_port_table": True}) is True
        # and by SHAPE alone, without the flag — so a future extractor that
        # forgets the flag is still corroborated
        assert P._v2060_record_declares_a_port_table(
            {"name": entry.get("name"), "extraction_strategy": strategy}
        ) is True, strategy


# ---------------------------------------------------------------------------
# 10. a width cell that DENIES its range does not publish it
#
# `phase1_port_extract::_signal_table_rows` arrived as a polarity offender with
# czport's v1.18.1 (the table width cell).  MEASURED on origin/main 45e2b9974
# BEFORE the consult existed:
#
#     'not [7:0]'            -> width 8
#     'no longer [7:0]'      -> width 8
#     'removed, was [7:0]'   -> width 8
#     'superseded by [15:0]' -> width 16
#     'obsolete: [3:0]'      -> width 4
#
# `_EMBEDDED_RANGE` searches ANYWHERE in the cell, so a row that RETIRES a range
# republished it as a declaration — #711's `die_area_budget_um` one field over.
# `not stated` / `no width` / `N/A` already came back WIDTH_UNKNOWN, but only
# because they carry no digits: nothing asked.
# ---------------------------------------------------------------------------
def _ppx_mod():
    import phase1_port_extract as _ppx  # noqa: WPS433
    return _ppx


@pytest.mark.parametrize("cell", [
    "not [7:0]", "no longer [7:0]", "removed, was [7:0]",
    "superseded by [15:0]", "obsolete: [3:0]",
])
def test_a_denied_range_is_not_published_as_a_width(cell):
    """THE DEFECT.  A denied width is not a width — it is WIDTH_UNKNOWN."""
    _ppx = _ppx_mod()
    assert _ppx._stated_width(cell) == _ppx.WIDTH_UNKNOWN, (
        f"the cell {cell!r} denies the range it contains and the reader "
        f"published {_ppx._stated_width(cell)} anyway")


@pytest.mark.parametrize("cell", ["not stated", "no width", "N/A", "n/a",
                                  "none", "unspecified"])
def test_a_cell_that_states_no_width_publishes_no_width(cell):
    """The control the ruling named.  True on both trees — and now for a
    REASON: it is asked, rather than falling out of the cell having no digit."""
    _ppx = _ppx_mod()
    assert _ppx._stated_width(cell) == _ppx.WIDTH_UNKNOWN


@pytest.mark.parametrize("cell,width", [
    ("8", 8), ("8 bits", 8), ("8-bit", 8), ("[7:0]", 8), ("[31:0]", 32),
    ("[0:0]", 1), ("1", 1), ("32", 32), ("16 bits wide", 16), ("64 bit", 64),
    ("2", 2),
])
def test_a_real_width_cell_is_unchanged(cell, width):
    """NO-LEAK.  29 of 34 cells in the lane's corpus did not move; these are
    the ones that state a width and must keep stating it."""
    assert _ppx_mod()._stated_width(cell) == width


def test_an_empty_cell_is_still_a_declared_one_bit_scalar():
    """The third answer must survive.  NO cell is a declaration of a 1-bit
    scalar; it is not a denial of anything, so the consult must not touch it."""
    _ppx = _ppx_mod()
    assert _ppx._stated_width("") == 1
    assert _ppx._stated_width("   ") == 1


@pytest.mark.parametrize("cell,width", [
    ("8 bits (not used)", 8),
    ("[7:0] (reserved)", 8),
    ("8 bits (not stated elsewhere)", 8),
])
def test_a_bracketed_qualifier_does_not_deny_the_width(cell, width):
    """#711's bracket rule reaches here through the shared helper.

    A qualifier in brackets carries a caveat, not the statement's polarity, so
    a cell that states a width and parenthesises a "not" still states it.  The
    cells are chosen so the width PARSES in the first place: `8 (not used)` is
    WIDTH_UNKNOWN on both trees because no rule reads a bare number followed by
    prose, which would make it a vacuous arm about nothing.
    """
    assert _ppx_mod()._stated_width(cell) == width


def test_the_row_walker_records_the_denial_word_it_found():
    """A refusal that names its evidence is checkable; a bare flag is not."""
    _ppx = _ppx_mod()
    rows = _ppx._signal_table_rows(
        "| Signal | Direction | Width |\n|---|---|---|\n"
        "| a | input | not [7:0] |\n| b | input | [3:0] |\n")
    assert rows["a"]["width_cell_denial"], rows["a"]
    assert rows["b"]["width_cell_denial"] is None, rows["b"]


def test_the_polarity_ratchet_passes_on_this_tree():
    """`--ratchet` rc=0: offenders are EXACTLY the register, by membership.

    And the register shrank the way the gate demands — the entry this lane
    fixed was deleted in the commit that fixed it, not left to rot.
    """
    import subprocess
    import prose_polarity_consulted_check as G  # noqa: WPS433
    plugin = _PROGRAMS.parent
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "prose_polarity_consulted_check.py"),
         "--root", str(plugin), "--ratchet"],
        capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "phase1_port_extract::_signal_table_rows" not in G._OFFENDER_REGISTER, (
        "the new offender was put in the register instead of being fixed")
    assert ("phase1_doc_one_shot_runner::_harvest_test_cases_from_input_tables"
            not in G._OFFENDER_REGISTER), (
        "the entry this lane fixed outlived its offender")
