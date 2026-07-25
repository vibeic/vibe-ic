"""ORGANIC — the plugin must never treat its OWN rendered layer-title heading
as evidence about the design.

DEFECT (measured on cell sha256 x gf180mcuD, plugin 1.5.85):
`phase1_dialogue_render` writes each layer heading from
`tools/phase1_engine/schema.LAYER_TITLES`, so every rendered doc contains

    ## L5 - Analog-Digital Interface (ADC/DAC, mixed-signal pads, PHY AFE)
           - NOT the vendor 'Analog Devices Inc.'

That line is a markdown heading, so `_v466_line_is_block_header` ranked it
ABOVE every prose hit and the `adc` / `dac` classes anchored on it. The
negation guard `_v0_1_62_analog_kw_negated` DOES correctly fire on the real
body sentence ("Purely digital synchronous block. No ADC, DAC, PHY AFE ..."),
but the emitter's `continue` advances to the next CLASS, never the next MATCH
- so the un-negated boilerplate occurrence won first and the negated real
sentence was never reached.

Result: two fabricated analog blocks on a pure-digital SHA-256 core, whose own
`evidence_paragraph` quotes the plugin's boilerplate verbatim. That drove an
entire A1-A9 analog track which wrote ngspice sizing/corner decks for hardware
that does not exist.

NARROWING (second pass). Recognising the boilerplate by SHAPE alone - any
`## L<n> -` heading - fixed the false positive by creating a false NEGATIVE.
The sole caller `gen_l5_adi_spec` runs this over the USER'S INPUT DOCS, and an
L-numbered heading is exactly the style this plugin's own layer scheme teaches
users to write, so a genuine mixed-signal spec whose ADC evidence sits under
`## L5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS` was silently dropped. The
boilerplate is now recognised by its ACTUAL RENDERED TEXT - the heading counts
as the plugin's own only when the text after the layer code EQUALS that layer's
canonical `schema.LAYER_TITLES` entry.

BIDIRECTIONAL:
  * `test_boilerplate_heading_alone_is_not_evidence` - the DEFECT case, checked
    END-TO-END: post-fix the chosen match must land on the real rationale
    sentence, where the negation guard fires and the block is SUPPRESSED.
    Pre-fix it lands on the boilerplate heading, where the guard does not
    fire, so the block is EMITTED - and this test FAILS.
  * `test_genuine_analog_prose_still_detected` - a real mixed-signal doc must
    STILL be detected, so the guard cannot suppress true positives.
  * `test_user_l_numbered_heading_is_not_plugin_boilerplate` and
    `test_genuine_adc_heading_under_l_number_still_detected` - the FALSE
    NEGATIVE the shape-only rule introduced. Both FAIL against it.
  * `test_plugin_layer_titles_are_loaded` - PREMISE: the narrowed rule is
    driven by the real title table; if that table cannot be loaded the guard
    goes inert and the R2 defect returns unnoticed.
  * `test_negated_body_sentence_still_negated` - the pre-existing negation
    guard must be untouched.
"""
import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


doc = _load("phase1_doc_one_shot_runner")

# byte-for-byte the heading the renderer emits for L5 (schema.LAYER_TITLES)
_L5_HEADING = ("## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
               "PHY AFE) — NOT the vendor 'Analog Devices Inc.'")
_ADC_PAT = doc._ANALOG_KEYWORDS["adc"]
_DAC_PAT = doc._ANALOG_KEYWORDS["dac"]

# REAL-SPEC headings a user writes in their OWN input doc, in the very
# L-numbered style this plugin's layer scheme teaches. None of them is the
# plugin's boilerplate; every one of them is design evidence. The shape-only
# rule `^#{1,6}\s*L\d+[A-Za-z]?\s*[dash]` suppressed all three.
_REAL_SPEC_HEADINGS = (
    "## L5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS",
    "## L5 — Analog front end (12-bit SAR ADC)",
    "### L2 - ADC channel budget",
)


def test_boilerplate_heading_alone_is_not_evidence():
    """THE DEFECT CASE, asserted END-TO-END.

    The emitter's decision is `match, then suppress if negated`. Pre-fix the
    chosen match sits on the plugin's own heading, where the negation guard
    does NOT fire -> block EMITTED (the fabrication). Post-fix the heading is
    excluded, so the chosen match lands on the real rationale sentence, where
    the guard DOES fire -> block SUPPRESSED. Assert exactly that pipeline."""
    text = "\n".join([
        _L5_HEADING,
        "",
        "- no_analog_in_input: True",
        "- rationale: Purely digital synchronous block. No ADC, DAC, PHY "
        "AFE, analog pad or mixed-signal interface of any kind.",
    ])
    for name, pat in (("adc", _ADC_PAT), ("dac", _DAC_PAT)):
        m = doc._v466_best_class_match(text, pat)
        assert m is not None, f"{name}: expected the rationale match"
        ls, le = doc._v466_line_bounds(text, m.start())
        line = text[ls:le]
        assert not doc._v466_line_is_plugin_layer_title(line), (
            f"{name} still anchored on plugin boilerplate: {line!r}")
        assert doc._v0_1_62_analog_kw_negated(text, m.start(), m.end()), (
            f"{name}: chosen match is not negated -> block would be EMITTED "
            f"on line {line!r}")


def test_heading_is_recognised_as_plugin_boilerplate():
    assert doc._v466_line_is_plugin_layer_title(_L5_HEADING)
    # ...and an ordinary design heading is NOT suppressed
    assert not doc._v466_line_is_plugin_layer_title(
        "## Analog front end — 12-bit SAR ADC")
    assert not doc._v466_line_is_plugin_layer_title("| adc | 12-bit | ")


def test_genuine_analog_prose_still_detected():
    """TRUE-POSITIVE GUARD. The suppression must be limited to the plugin's
    own heading grammar - a real mixed-signal spec must still be detected,
    even when the boilerplate heading is also present."""
    text = "\n".join([
        _L5_HEADING,
        "",
        "- adc_type: 12-bit SAR ADC, 1 MSPS, single-ended input",
        "- reference: on-chip bandgap voltage reference feeds the ADC",
    ])
    m = doc._v466_best_class_match(text, _ADC_PAT)
    assert m is not None, "suppressed a GENUINE analog block"
    line = text[doc._v466_line_bounds(text, m.start())[0]:
                doc._v466_line_bounds(text, m.start())[1]]
    assert "adc_type" in line or "bandgap" in line, (
        f"matched the wrong line: {line!r}")


def test_plugin_layer_titles_are_loaded():
    """PREMISE GUARD. The narrowed rule compares against the plugin's REAL
    rendered titles (`tools/phase1_engine/schema.LAYER_TITLES`). If that table
    cannot be loaded the comparison can never match, the suppression silently
    goes inert and the R2 self-contamination defect returns with a green
    suite. Assert the premise instead of trusting it."""
    titles = doc._v466_plugin_layer_titles()
    assert titles, ("schema.LAYER_TITLES unreachable — the self-contamination "
                    "guard would be inert")
    assert "L5" in titles and titles["L5"], titles.get("L5")
    # the boilerplate constant above must still BE the rendered heading
    assert doc._v466_norm_layer_title(
        _L5_HEADING.split("L5", 1)[1].lstrip(" —–-")) == titles["L5"]


def test_user_l_numbered_heading_is_not_plugin_boilerplate():
    """FALSE-NEGATIVE GUARD, at the predicate. A user's own L-numbered heading
    carries the user's own words and is NOT the plugin's boilerplate."""
    for h in _REAL_SPEC_HEADINGS:
        assert not doc._v466_line_is_plugin_layer_title(h), (
            f"suppressed a REAL spec heading as boilerplate: {h!r}")
    # ...while the plugin's own full L5 heading still IS boilerplate
    assert doc._v466_line_is_plugin_layer_title(_L5_HEADING)


def test_genuine_adc_heading_under_l_number_still_detected():
    """FALSE-NEGATIVE GUARD, end-to-end and ON A HEADING (not in a bullet).

    The evidence sits on the heading itself, exactly as it does in a real
    mixed-signal spec, and the plugin's own boilerplate heading is present in
    the same doc. The chosen match must land on the USER'S heading."""
    for h in _REAL_SPEC_HEADINGS:
        text = "\n".join([
            _L5_HEADING,
            "",
            h,
            "",
            "Sampled at 1 MSPS from a 3.3 V single-ended source.",
        ])
        m = doc._v466_best_class_match(text, _ADC_PAT)
        assert m is not None, (
            f"suppressed a GENUINE analog heading, no evidence left: {h!r}")
        ls, le = doc._v466_line_bounds(text, m.start())
        assert text[ls:le] == h, (
            f"expected the match on {h!r}, got {text[ls:le]!r}")


def test_negated_body_sentence_still_negated():
    """The pre-existing negation guard must be unchanged by this fix."""
    neg = "Purely digital block. No ADC, DAC, PHY AFE, analog pad."
    i = neg.index("ADC")
    assert doc._v0_1_62_analog_kw_negated(neg, i, i + 3)
    pos = "12-bit SAR ADC, 1 MSPS, single-ended input"
    j = pos.index("ADC")
    assert not doc._v0_1_62_analog_kw_negated(pos, j, j + 3)
