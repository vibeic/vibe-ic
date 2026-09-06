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
